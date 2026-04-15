import json
import os
import tempfile
from pathlib import Path

import httpx
import uvicorn
from azure.storage.blob import BlobServiceClient
from cloudevents.v1.conversion import to_structured
from cloudevents.v1.http import CloudEvent, from_http
from docling.document_converter import DocumentConverter
from fastapi import FastAPI, Request, Response

# Output channel URL — update this to match your cluster/namespace
OUTPUT_CHANNEL_URL = os.environ.get(
    "OUTPUT_CHANNEL_URL",
    "http://docling-process-output.sandbox.svc.cluster.local",
)

# Azure Blob Storage connection string
AZURE_STORAGE_CONNECTION_STRING = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")

app = FastAPI()


def parse_event_data(event) -> dict:
    """Extract and JSON-decode the CloudEvent data payload."""
    data = event.data
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8")
    if isinstance(data, str):
        data = json.loads(data)
    return data


def validate_payload(data: dict) -> tuple[dict, dict]:
    """Validate that the payload contains input and output blob references."""
    if "input" not in data or "output" not in data:
        raise ValueError("Payload must contain 'input' and 'output' fields")

    inp = data["input"]
    out = data["output"]

    for field in ("container", "path"):
        if field not in inp:
            raise ValueError(f"'input' is missing required field: '{field}'")
        if field not in out:
            raise ValueError(f"'output' is missing required field: '{field}'")

    return inp, out


def download_blob(client: BlobServiceClient, container: str, blob_path: str, dest: Path) -> None:
    """Download a blob from Azure Blob Storage to a local file."""
    blob = client.get_blob_client(container=container, blob=blob_path)
    with open(dest, "wb") as f:
        stream = blob.download_blob()
        stream.readinto(f)
    print(f"[Azure] Downloaded blob {container}/{blob_path} -> {dest}")


def upload_blob(client: BlobServiceClient, container: str, blob_path: str, src: Path) -> None:
    """Upload a local file to Azure Blob Storage."""
    blob = client.get_blob_client(container=container, blob=blob_path)
    with open(src, "rb") as f:
        blob.upload_blob(f, overwrite=True)
    print(f"[Azure] Uploaded {src} -> {container}/{blob_path}")


def upload_directory(client: BlobServiceClient, container: str, blob_prefix: str, src_dir: Path) -> None:
    """Upload all files in a local directory to Azure Blob Storage under a prefix."""
    for file in src_dir.rglob("*"):
        if file.is_file():
            relative = file.relative_to(src_dir)
            blob_path = f"{blob_prefix.rstrip('/')}/{relative}"
            upload_blob(client, container, blob_path, file)


@app.post("/")
async def handle_event(request: Request) -> Response:
    body = await request.body()
    event = from_http(request.headers, body)

    print(f"[CloudEvent received] id={event['id']} type={event['type']} source={event['source']}")

    try:
        data = parse_event_data(event)
        print(f"[Payload] {data}")

        inp, out = validate_payload(data)
        print(f"[Input]  container={inp['container']} path={inp['path']}")
        print(f"[Output] container={out['container']} path={out['path']}")

    except (ValueError, json.JSONDecodeError, KeyError) as exc:
        print(f"[Error] Invalid payload: {exc}")
        return Response(status_code=400, content=str(exc))

    blob_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        input_file = tmp / Path(inp["path"]).name
        output_dir = tmp / "output"
        output_dir.mkdir()

        # Download input file from Azure Blob Storage
        download_blob(blob_client, inp["container"], inp["path"], input_file)

        # Convert document with docling
        print(f"[Docling] Converting {input_file}")
        converter = DocumentConverter()
        result = converter.convert(str(input_file))

        stem = input_file.stem
        (output_dir / f"{stem}.md").write_text(
            result.document.export_to_markdown(), encoding="utf-8"
        )
        (output_dir / f"{stem}.json").write_text(
            json.dumps(result.document.export_to_dict(), indent=2), encoding="utf-8"
        )
        print(f"[Docling] Conversion complete, artifacts written to {output_dir}")

        # Upload output files to Azure Blob Storage
        upload_directory(blob_client, out["container"], out["path"], output_dir)

    # Publish result event to output channel
    result_event = CloudEvent(
        {
            "type": "com.docling.document.processed",
            "source": "docling-process-function",
        },
        {
            "input": inp,
            "output": out,
            "status": "success",
        },
    )
    headers, result_body = to_structured(result_event)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(OUTPUT_CHANNEL_URL, headers=headers, content=result_body, timeout=10)
        print(f"[Published] status={resp.status_code} channel={OUTPUT_CHANNEL_URL}")
    except httpx.RequestError as exc:
        print(f"[Publish failed] {exc}")

    return Response(status_code=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
