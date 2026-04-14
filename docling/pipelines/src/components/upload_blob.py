from kfp import dsl
from kfp.dsl import Input, Dataset

_BASE_IMAGE = "python:3.11-slim"
_PACKAGES = ["requests"]


@dsl.component(base_image=_BASE_IMAGE, packages_to_install=_PACKAGES)
def upload_blob_op(
    container_name: str,
    blob_name: str,
    input_file: Input[Dataset],
    storage_account: str = "",
    storage_key: str = "",
) -> None:
    """
    Upload the *input_file* artifact to *container_name* as a BlockBlob
    named *blob_name*.

    Parameters
    ----------
    container_name  : destination container
    blob_name       : path/name to assign the blob in the container
    input_file      : input artifact whose bytes are uploaded
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

    with open(input_file.path, "rb") as fh:
        data = fh.read()

    content_length = str(len(data))
    account = _account()
    url = f"https://{account}.blob.core.windows.net/{container_name}/{quote(blob_name, safe='/')}"
    extra = {"Content-Type": "application/octet-stream", "x-ms-blob-type": "BlockBlob"}
    headers = _build_headers(
        "PUT", container_name, blob=blob_name, extra=extra, clen=content_length
    )
    headers["Content-Length"] = content_length

    print(f"[INFO] Uploading {content_length} bytes -> '{container_name}/{blob_name}'")
    resp = requests.put(url, headers=headers, data=data)
    if not resp.ok:
        print(f"[ERROR] upload_blob failed: {resp.status_code} {resp.text}")
        resp.raise_for_status()

    print(f"[INFO] Upload complete: '{blob_name}'")
