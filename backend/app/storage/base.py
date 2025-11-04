from __future__ import annotations

from typing import Protocol, BinaryIO
import uuid


class StorageBackend(Protocol):
    """Abstract storage backend interface.

    Each implementation is responsible for persisting and retrieving binary file
    objects using an opaque storage key string.
    """

    def put(self, file_id: uuid.UUID, src_stream: BinaryIO, ext: str) -> str:
        """Store bytes from src_stream under a key derived from file_id and ext.

        The implementation may read from the src_stream's current position until EOF.
        Returns a storage_key string that can later be provided to get/size/delete.
        May raise OSError/IOError on I/O errors.
        """
        ...

    def get(self, storage_key: str) -> bytes:
        """Return the stored file's full bytes for the given storage_key.

        May raise FileNotFoundError if the key does not exist.
        """
        ...

    def delete(self, storage_key: str) -> None:
        """Delete the stored object by storage_key. No-op if missing."""
        ...

    def size(self, storage_key: str) -> int:
        """Return the stored object's size in bytes.

        May raise FileNotFoundError if the key does not exist.
        """
        ...
