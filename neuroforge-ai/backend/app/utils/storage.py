"""Object storage abstraction: local filesystem or any S3-compatible store."""
from __future__ import annotations

import tempfile
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, ValidationFailed


class StorageBackend(ABC):
    @abstractmethod
    def save(self, key: str, data: bytes) -> None: ...

    @abstractmethod
    def read(self, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    def local_path(self, key: str) -> Path:
        """A real filesystem path for libraries that need one (downloads from remote stores)."""
        suffix = Path(key).suffix
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(self.read(key))
        tmp.close()
        return Path(tmp.name)


class LocalStorage(StorageBackend):
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        if not key or key.startswith(("/", "\\")) or ".." in Path(key.replace("\\", "/")).parts:
            raise ValidationFailed("Invalid storage key")
        path = (self.root / key).resolve()
        if self.root != path and self.root not in path.parents:  # path traversal guard
            raise ValidationFailed("Invalid storage key")
        return path

    def save(self, key: str, data: bytes) -> None:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def read(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.exists():
            raise NotFoundError(f"Stored object not found: {key}")
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        return self._resolve(key).exists()

    def delete(self, key: str) -> None:
        path = self._resolve(key)
        if path.exists():
            path.unlink()

    def local_path(self, key: str) -> Path:
        path = self._resolve(key)
        if not path.exists():
            raise NotFoundError(f"Stored object not found: {key}")
        return path


class S3Storage(StorageBackend):
    def __init__(self, bucket: str, endpoint_url: str = "", region: str = "us-east-1",
                 access_key: str = "", secret_key: str = ""):
        import boto3

        if not bucket:
            raise ValidationFailed("S3_BUCKET is required when STORAGE_BACKEND=s3")
        self.bucket = bucket
        self.client = boto3.client(
            "s3", endpoint_url=endpoint_url or None, region_name=region,
            aws_access_key_id=access_key or None, aws_secret_access_key=secret_key or None,
        )

    def save(self, key: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)

    def read(self, key: str) -> bytes:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self.client.exceptions.NoSuchKey as e:
            raise NotFoundError(f"Stored object not found: {key}") from e

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


@lru_cache
def get_storage() -> StorageBackend:
    s = get_settings()
    if s.storage_backend == "s3":
        return S3Storage(s.s3_bucket, s.s3_endpoint_url, s.s3_region, s.s3_access_key_id, s.s3_secret_access_key)
    return LocalStorage(s.storage_dir)
