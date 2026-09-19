"""Storage-domain exceptions with stable error codes."""

from __future__ import annotations


class StorageError(Exception):
    """Raised for any storage-layer failure. The ``code`` is safe to expose in API responses."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)
