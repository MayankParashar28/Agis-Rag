"""Where original uploaded files live.

Two backends:
- ``local``: files stay on the server's disk under ``uploads/``. Fine for a
  single machine, but lost on hosts that wipe the disk on every deploy.
- ``s3``: any S3-compatible bucket (AWS S3, Cloudflare R2, Supabase Storage,
  MinIO). Survives redeploys, lets the API and worker run on different
  machines, and removes the Redis size limit for large files because the
  worker can always fetch the original from the bucket.

Both expose the same small interface; callers never touch boto3 directly.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from typing import Iterator, Optional

from app.core.config import settings
from app.core.logging import logger


def _upload_dir() -> str:
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(base, "uploads")
    os.makedirs(path, exist_ok=True)
    return path


class LocalStorage:
    backend = "local"

    def _path(self, key: str) -> str:
        return os.path.join(_upload_dir(), os.path.basename(key))

    def put_file(self, key: str, local_path: str) -> None:
        dest = self._path(key)
        if os.path.abspath(dest) != os.path.abspath(local_path):
            shutil.copyfile(local_path, dest)

    def exists(self, key: str) -> bool:
        return os.path.exists(self._path(key))

    def download_to(self, key: str, dest_path: str) -> None:
        shutil.copyfile(self._path(key), dest_path)

    def stream(self, key: str, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        with open(self._path(key), "rb") as f:
            while chunk := f.read(chunk_size):
                yield chunk

    def delete(self, key: str) -> None:
        try:
            os.remove(self._path(key))
        except FileNotFoundError:
            pass

    def size(self, key: str) -> Optional[int]:
        try:
            return os.path.getsize(self._path(key))
        except OSError:
            return None


class S3Storage:
    backend = "s3"

    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        self.bucket = settings.S3_BUCKET
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL or None,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID or None,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY or None,
            region_name=settings.S3_REGION or None,
            config=Config(s3={"addressing_style": "path"} if settings.S3_ENDPOINT_URL else {}),
        )

    def put_file(self, key: str, local_path: str) -> None:
        self.client.upload_file(local_path, self.bucket, key)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def download_to(self, key: str, dest_path: str) -> None:
        self.client.download_file(self.bucket, key, dest_path)

    def stream(self, key: str, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        for chunk in body.iter_chunks(chunk_size):
            yield chunk

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as e:
            logger.warning(f"Could not delete {key} from bucket {self.bucket}: {e}")

    def size(self, key: str) -> Optional[int]:
        try:
            return int(self.client.head_object(Bucket=self.bucket, Key=key)["ContentLength"])
        except Exception:
            return None


_storage = None


def get_storage():
    """The configured backend; falls back to local with a warning if the S3
    settings are incomplete, so a typo never stops uploads."""
    global _storage
    if _storage is None:
        if settings.STORAGE_BACKEND == "s3":
            if not settings.S3_BUCKET:
                logger.warning("STORAGE_BACKEND=s3 but S3_BUCKET is not set; using local storage.")
                _storage = LocalStorage()
            else:
                try:
                    _storage = S3Storage()
                    logger.info(f"Object storage: S3 bucket '{settings.S3_BUCKET}'"
                                f"{' at ' + settings.S3_ENDPOINT_URL if settings.S3_ENDPOINT_URL else ''}.")
                except Exception as e:
                    logger.error(f"Could not initialise S3 storage ({e}); using local storage.")
                    _storage = LocalStorage()
        else:
            _storage = LocalStorage()
    return _storage


def reset() -> None:
    global _storage
    _storage = None


def storage_key(doc_id, ext: str) -> str:
    return f"uploads/{doc_id}{ext.lower()}"


async def fetch_to_temp(key: str, ext: str) -> Optional[str]:
    """Download an original into a temp file (for re-indexing / the worker).
    Returns the path, or None if the object does not exist."""
    store = get_storage()
    if not await asyncio.to_thread(store.exists, key):
        return None
    fd, path = tempfile.mkstemp(prefix="aegis_src_", suffix=ext.lower())
    os.close(fd)
    await asyncio.to_thread(store.download_to, key, path)
    return path


def describe() -> dict:
    store = get_storage()
    return {
        "backend": store.backend,
        "bucket": settings.S3_BUCKET if store.backend == "s3" else None,
        "endpoint": settings.S3_ENDPOINT_URL if store.backend == "s3" else None,
    }
