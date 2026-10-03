"""Storage port — local disk + in-memory fake. Artifact identity is storage_key."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class StoragePort(Protocol):
    def put(self, storage_key: str, data: bytes) -> None: ...

    def get(self, storage_key: str) -> bytes: ...

    def exists(self, storage_key: str) -> bool: ...

    def delete(self, storage_key: str) -> None: ...


class LocalDiskStorage:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, storage_key: str) -> Path:
        key = storage_key.replace("\\", "/").lstrip("/")
        if ".." in key.split("/"):
            raise ValueError(f"Invalid storage_key: {storage_key}")
        return self.root / key

    def put(self, storage_key: str, data: bytes) -> None:
        path = self._path(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, storage_key: str) -> bytes:
        path = self._path(storage_key)
        if not path.is_file():
            raise FileNotFoundError(storage_key)
        return path.read_bytes()

    def exists(self, storage_key: str) -> bool:
        return self._path(storage_key).is_file()

    def delete(self, storage_key: str) -> None:
        path = self._path(storage_key)
        if path.is_file():
            path.unlink()


class FakeStorage:
    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def put(self, storage_key: str, data: bytes) -> None:
        self._objects[storage_key] = data

    def get(self, storage_key: str) -> bytes:
        try:
            return self._objects[storage_key]
        except KeyError as exc:
            raise FileNotFoundError(storage_key) from exc

    def exists(self, storage_key: str) -> bool:
        return storage_key in self._objects

    def delete(self, storage_key: str) -> None:
        self._objects.pop(storage_key, None)

    def clear(self) -> None:
        self._objects.clear()


_storage_singleton: StoragePort | None = None


def get_storage() -> StoragePort:
    global _storage_singleton
    if _storage_singleton is None:
        from django.conf import settings

        if settings.ENVIRONMENT == "test":
            _storage_singleton = FakeStorage()
        else:
            _storage_singleton = LocalDiskStorage(settings.STORAGE_ROOT)
    return _storage_singleton


def set_storage_for_tests(storage: StoragePort | None) -> None:
    global _storage_singleton
    _storage_singleton = storage
