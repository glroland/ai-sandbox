from typing import List
from kfp import dsl

_BASE_IMAGE = "python:3.11-slim"
_PACKAGES = ["requests"]


@dsl.component(base_image=_BASE_IMAGE, packages_to_install=_PACKAGES)
def list_blobs_op(
    container_name: str,
    storage_account: str = "",
    storage_key: str = "",
) -> List[str]:
    """
    List all blob names in *container_name* and return them as a list of strings.

    Parameters
    ----------
    container_name  : Azure Blob Storage container to list
    storage_account : override AZURE_STORAGE_ACCOUNT env var (optional)
    storage_key     : override AZURE_STORAGE_KEY env var (optional)
    """
    import base64, datetime, hashlib, hmac, os, xml.etree.ElementTree as ET
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

    account = _account()
    params = {"restype": "container", "comp": "list"}
    url = f"https://{account}.blob.core.windows.net/{container_name}"
    headers = _build_headers("GET", container_name, qp=params)

    print(f"[INFO] Listing blobs in container '{container_name}'")
    resp = requests.get(url, headers=headers, params=params)
    if not resp.ok:
        print(f"[ERROR] list_blobs failed: {resp.status_code} {resp.text}")
        resp.raise_for_status()

    root = ET.fromstring(resp.text)
    names = [n.find("Name").text for n in root.iter("Blob")]
    print(f"[INFO] Found {len(names)} blob(s)")
    return names
