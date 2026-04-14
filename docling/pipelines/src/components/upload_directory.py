from kfp import dsl
from kfp.dsl import Input, Dataset

_BASE_IMAGE = "python:3.11-slim"
_PACKAGES = ["requests"]


@dsl.component(base_image=_BASE_IMAGE, packages_to_install=_PACKAGES)
def upload_directory_op(
    container_name: str,
    blob_prefix: str,
    input_dir: Input[Dataset],
    storage_account: str = "",
    storage_key: str = "",
) -> None:
    """
    Upload every file in *input_dir* to *container_name*.

    Each file is stored as ``{blob_prefix}/{relative_path}`` where
    *relative_path* is the file's path relative to *input_dir*.

    Parameters
    ----------
    container_name  : destination container
    blob_prefix     : prefix prepended to every uploaded blob name
    input_dir       : input artifact directory whose files are uploaded
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
        hdrs = {"x-ms-date": utc, "x-ms-version": "2020-10-02"}
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

    def _upload_file(local_path: str, blob_name: str):
        with open(local_path, "rb") as fh:
            data = fh.read()
        content_length = str(len(data))
        account = _account()
        url = f"https://{account}.blob.core.windows.net/{container_name}/{quote(blob_name, safe='/')}"
        extra = {"Content-Type": "application/octet-stream", "x-ms-blob-type": "BlockBlob"}
        headers = _build_headers(
            "PUT", container_name, blob=blob_name, extra=extra, clen=content_length
        )
        headers["Content-Length"] = content_length
        print(f"[INFO] Uploading {content_length} bytes → '{container_name}/{blob_name}'")
        resp = requests.put(url, headers=headers, data=data)
        if not resp.ok:
            print(f"[ERROR] upload failed: {resp.status_code} {resp.text}")
            resp.raise_for_status()
        print(f"[INFO] Upload complete: '{blob_name}'")

    base_dir = input_dir.path
    prefix = blob_prefix.rstrip("/")
    for dirpath, _, filenames in os.walk(base_dir):
        for filename in filenames:
            local_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(local_path, base_dir)
            blob_name = f"{prefix}/{rel_path}"
            _upload_file(local_path, blob_name)
