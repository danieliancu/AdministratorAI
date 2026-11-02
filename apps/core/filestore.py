"""Files uploaded by a firm. Content-addressed under the tenant, never overwritten."""

import hashlib
import uuid
from pathlib import Path, PurePosixPath

from django.conf import settings


def _root():
    return Path(settings.TENANT_FILE_ROOT)


def put(tenant_id, content):
    checksum = hashlib.sha256(content).hexdigest()
    key = f"{tenant_id}/{checksum[:2]}/{checksum}"
    path = _root() / key
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(content)
        temporary.replace(path)
    return key, checksum


def get(tenant_id, key):
    # The key comes from a row the caller could read; the prefix check is a second lock.
    parts = PurePosixPath(key).parts
    if not parts or parts[0] != str(tenant_id) or ".." in parts:
        raise PermissionError("File does not belong to this tenant")
    return (_root() / key).read_bytes()
