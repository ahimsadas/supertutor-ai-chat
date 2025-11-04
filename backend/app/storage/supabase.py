from __future__ import annotations

"""Supabase Storage backend for binary file persistence.

Uses the existing Supabase client helper to access the Storage bucket.
This is the single, canonical storage backend in this codebase.
"""

import os
import uuid
import mimetypes
import tempfile
from logging import getLogger
from typing import BinaryIO, Any, Tuple

from app.clients.supabase_client import get_supabase_client
from app.core.config import get_settings
from .base import StorageBackend


logger = getLogger("supertutor.storage.supabase")


def _normalize_ext(ext: str) -> str:
    e = (ext or "").strip()
    if not e:
        return ".bin"
    if not e.startswith("."):
        e = "." + e
    return e


class SupabaseStorage(StorageBackend):
    """Supabase-backed implementation of StorageBackend.

    - Bucket name: env SUPABASE_FILES_BUCKET (default "files").
    - Key convention: f"files/{file_id}{ext}".
    """

    def __init__(self) -> None:
        self._client = get_supabase_client()
        s = get_settings()
        self._bucket_name = (getattr(s, "SUPABASE_FILES_BUCKET", "files") or "files").strip() or "files"
        self._bucket_ready = False
        logger.info("supabase.storage.init bucket=%s", self._bucket_name)

    def _bucket_api(self):
        self._ensure_bucket()
        return self._client.storage.from_(self._bucket_name)

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            storage = self._client.storage
            exists = False
            # Try get_bucket if available
            try:
                gb = getattr(storage, "get_bucket", None)
                if callable(gb):
                    res = gb(self._bucket_name)
                    # Some SDKs return dict with 'name'
                    if res:
                        exists = True
                else:
                    # Fallback: list buckets and search by name
                    lb = getattr(storage, "list_buckets", None)
                    if callable(lb):
                        items = lb()
                        for it in (items or []):
                            name = it.get("name") if isinstance(it, dict) else getattr(it, "name", None)
                            if name == self._bucket_name:
                                exists = True
                                break
            except Exception:
                # If probing fails, we'll attempt to create and handle errors
                pass

            if not exists:
                created = False
                try:
                    cb = getattr(storage, "create_bucket", None)
                    if callable(cb):
                        # Prefer non-public bucket
                        cb(self._bucket_name, {"public": False})
                        created = True
                        logger.info("supabase.storage.bucket.created name=%s", self._bucket_name)
                except Exception:
                    logger.debug("supabase.storage.bucket.create.failed name=%s", self._bucket_name)
                if not created:
                    raise RuntimeError(
                        f"Supabase bucket '{self._bucket_name}' not found. Set SUPABASE_FILES_BUCKET or create the bucket in the dashboard."
                    )

            self._bucket_ready = True
        except Exception:
            logger.exception("supabase.storage.bucket.preflight.failed name=%s", self._bucket_name)
            raise

    def put(self, file_id: uuid.UUID, src_stream: BinaryIO, ext: str) -> str:
        """Upload content to Supabase Storage and return the storage key.

        Accepts bytes, path-like, or file-like. File-like is spooled to a temporary
        file before upload because storage3.upload expects a filesystem path.
        """
        ext_norm = _normalize_ext(ext)
        key = f"files/{str(file_id)}{ext_norm}"
        content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"

        tmp_path: str = ""
        needs_cleanup = False
        bytes_written = -1

        def _to_temp_path(obj: Any, suffix: str) -> Tuple[str, int, bool]:
            if isinstance(obj, (bytes, bytearray)):
                f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                try:
                    f.write(obj)
                    f.flush()
                    os.fsync(f.fileno())
                    return f.name, len(obj), True
                finally:
                    f.close()
            # Path-like (use directly)
            if isinstance(obj, (str, os.PathLike)):
                p = os.fspath(obj)
                try:
                    st = os.stat(p)
                    size = int(st.st_size)
                except Exception:
                    size = -1
                return p, size, False
            # File-like: copy in chunks
            if hasattr(obj, "read"):
                f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                try:
                    # best effort seek to start
                    try:
                        obj.seek(0)  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    total = 0
                    with open(f.name, "wb") as out:
                        while True:
                            chunk = obj.read(1024 * 1024)
                            if not chunk:
                                break
                            out.write(chunk)
                            total += len(chunk)
                        out.flush()
                        os.fsync(out.fileno())
                    return f.name, total, True
                finally:
                    try:
                        f.close()
                    except Exception:
                        pass
            # Fallback: convert to bytes and write
            data = bytes(obj)
            f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            try:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
                return f.name, len(data), True
            finally:
                f.close()

        tmp_path, bytes_written, needs_cleanup = _to_temp_path(src_stream, ext_norm)
        logger.debug("supabase.put.begin bucket=%s key=%s tmp=%s size=%s", self._bucket_name, key, tmp_path, bytes_written)

        try:
            # storage3 expects (key, local_path, options)
            self._bucket_api().upload(key, tmp_path, {"content-type": content_type})
        except Exception:
            logger.exception("supabase.put failed bucket=%s key=%s tmp=%s", self._bucket_name, key, tmp_path)
            raise
        finally:
            if needs_cleanup and tmp_path:
                try:
                    os.remove(tmp_path)
                except Exception:
                    logger.debug("supabase.put.cleanup failed tmp=%s", tmp_path)

        logger.debug("supabase.put.done bucket=%s key=%s bytes=%s", self._bucket_name, key, bytes_written)
        return key

    def get(self, storage_key: str) -> bytes:
        """Download and return the object's bytes.

        Raises FileNotFoundError if missing, otherwise raises the underlying error.
        """
        logger.debug("supabase.get bucket=%s key=%s", self._bucket_name, storage_key)
        try:
            data = self._bucket_api().download(storage_key)
        except Exception as e:
            msg = (str(e) or "").lower()
            if "not found" in msg or "404" in msg:
                raise FileNotFoundError(storage_key)
            raise
        # supabase-py typically returns bytes for download
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
        # Fallbacks for variants returning Response-like objects
        try:
            content = getattr(data, "content", None)
            if content is not None:
                return bytes(content)
        except Exception:
            pass
        try:
            if hasattr(data, "read"):
                return data.read()
        except Exception:
            pass
        return bytes(data)

    def delete(self, storage_key: str) -> None:
        """Delete the object; missing keys are treated as no-op."""
        logger.debug("supabase.delete bucket=%s key=%s", self._bucket_name, storage_key)
        try:
            self._bucket_api().remove([storage_key])
        except Exception as e:
            msg = (str(e) or "").lower()
            if "not found" in msg or "404" in msg:
                return
            raise

    def size(self, storage_key: str) -> int:
        """Return object size in bytes.

        Tries to use list metadata; if unavailable, falls back to download length.
        """
        logger.debug("supabase.size bucket=%s key=%s", self._bucket_name, storage_key)
        # Try to get size via list metadata
        try:
            if "/" in storage_key:
                dir_part, file_part = storage_key.rsplit("/", 1)
            else:
                dir_part, file_part = "", storage_key
            items = self._bucket_api().list(dir_part or "")
            for it in items or []:
                name = (it.get("name") if isinstance(it, dict) else getattr(it, "name", None))
                if name == file_part:
                    # size may be present directly or under metadata
                    if isinstance(it, dict):
                        sz = it.get("size")
                        if isinstance(sz, int):
                            return sz
                        meta = it.get("metadata")
                        if isinstance(meta, dict):
                            msz = meta.get("size")
                            if isinstance(msz, int):
                                return msz
                    else:
                        sz_attr = getattr(it, "size", None)
                        if isinstance(sz_attr, int):
                            return sz_attr
                        meta = getattr(it, "metadata", None)
                        if isinstance(meta, dict):
                            msz = meta.get("size")
                            if isinstance(msz, int):
                                return msz
        except Exception:
            # fall back to download
            pass
        # Fallback: download and measure
        data = self.get(storage_key)
        return len(data)
