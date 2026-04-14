from kfp import dsl
from kfp.dsl import Output, Dataset

_BASE_IMAGE = "python:3.11-slim"
_PACKAGES = ["requests"]


@dsl.component(base_image=_BASE_IMAGE, packages_to_install=_PACKAGES)
def download_blob_op(
    container_name: str,
    blob_name: str,
    output_file: Output[Dataset],
    storage_account: str = "",
    storage_key: str = "",
) -> None:
    """
    Download *blob_name* from *container_name* and expose it as the
    *output_file* artifact for downstream components.

    Parameters
    ----------
    container_name  : source container
    blob_name       : path/name of the blob to download
    output_file     : output artifact that receives the downloaded bytes
    storage_account : override AZURE_STORAGE_ACCOUNT env var (optional)
    storage_key     : override AZURE_STORAGE_KEY env var (optional)
    """
    import base64, datetime, hashlib, hmac, os
    from urllib.parse import quote
    import requests

    def _account() -> str:
        v = storage_account or os.environ.get("AZURE_STORAGE_ACCOUNT", "")
        if not v:
            raise EnvironmentError("AZURE_STORAGE_ACCOUNT is not set")
        return v

    def _key() -> str:
        v = storage_key or os.environ.get("AZURE_STORAGE_KEY", "")
        if not v:
            raise EnvironmentError("AZURE_STORAGE_KEY is not set")
        return v

    def _sign(s: str) -> str:
        raw = base64.b64decode(_key())
        return base64.b64encode(
            hmac.new(raw, s.encode("utf-8"), hashlib.sha256).digest()
        ).decode()

    def _build_headers(method, container, blob=None, extra=None, qp=None, clen=""):
        account = _account()
        utc = datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")
        hdrs = {"x-ms-date": utc, "x-ms-version": "2025-11-05"}
        if extra:
            hdrs.update(extra)
        ms = sorted((k.lower(), v) for k, v in hdrs.items() if k.lower().startswith("x-ms-"))
        canon_hdrs = "".join(f"{k}:{v}\n" for k, v in ms)
        resource = f"/{account}/{container}"
        if blob:
            resource += f"/{blob}"
        if qp:
            for k in sorted(qp):
                resource += f"\n{k}:{qp[k]}"
        sts = (
            f"{method}\n\n\n{clen}\n"
            f"{hdrs.get('Content-MD5','')}\n{hdrs.get('Content-Type','')}\n"
            f"\n\n\n\n\n\n{canon_hdrs}{resource}"
        )
        hdrs["Authorization"] = f"SharedKey {account}:{_sign(sts)}"
        return hdrs

    print(f"[INFO] Downloading File -> {output_file.path}")

    account = _account()
    url = f"https://{account}.blob.core.windows.net/{container_name}/{quote(blob_name, safe='/')}"
    headers = _build_headers("GET", container_name, blob=blob_name)

    print(f"[INFO] Downloading '{blob_name}' from '{container_name}'")
    resp = requests.get(url, headers=headers, stream=True)
    if not resp.ok:
        print(f"[ERROR] download_blob failed: {resp.status_code} {resp.text}")
        resp.raise_for_status()

    with open(output_file.path, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=65536):
            fh.write(chunk)

    print(f"[INFO] Download complete -> {output_file.path}")
