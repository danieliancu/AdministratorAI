"""Object storage adapter for original documents. Local disk now, replaceable later."""

import hashlib
from pathlib import Path

from django.conf import settings


class ObjectStore:
    def put(self, content: bytes) -> tuple[str, str]:
        raise NotImplementedError

    def get(self, key: str) -> bytes:
        raise NotImplementedError


class LocalObjectStore(ObjectStore):
    """Content-addressed, so an identical document is stored once and never overwritten."""

    def __init__(self, root=None):
        self.root = Path(root or settings.LEGAL_OBJECT_ROOT)

    def put(self, content):
        checksum = hashlib.sha256(content).hexdigest()
        key = f"{checksum[:2]}/{checksum}"
        path = self.root / key
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(content)
            temporary.replace(path)
        return key, checksum

    def get(self, key):
        return (self.root / key).read_bytes()


def get_store():
    return LocalObjectStore()
