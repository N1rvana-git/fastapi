"""File storage adapters.

Highlights vs. the previous implementation:

* filenames are generated (uuid4) - the user-supplied name never touches the
  filesystem, which removes the path-traversal risk of ``f"uploads/{filename}"``;
* extension + magic-byte validation and a hard byte limit;
* blocking disk I/O is pushed to a thread (``asyncio.to_thread``) so it cannot
  stall the event loop;
* the storage backend is a strategy behind a Protocol, so moving to object
  storage is a config change, not a rewrite.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from fastapi import UploadFile

from src.app.core.config import Settings
from src.app.core.exceptions import (
    BusinessRuleViolation,
    FeatureUnavailableError,
    PayloadTooLargeError,
)
from src.app.core.logging import get_logger

logger = get_logger(__name__)

_IMAGE_MAGIC = {
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "gif": (b"GIF87a", b"GIF89a"),
    "webp": (b"RIFF",),
}


@dataclass(frozen=True)
class StoredImage:
    filename: str
    url: str
    size: int
    content_type: str


class StorageProvider(Protocol):
    async def save(self, upload: UploadFile, *, prefix: str = "items") -> StoredImage: ...


def _extension(filename: str | None) -> str:
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


class LocalStorage:
    """Store files on the local volume and serve them via ``/uploads``."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.upload_dir
        self.root.mkdir(parents=True, exist_ok=True)

    async def save(self, upload: UploadFile, *, prefix: str = "items") -> StoredImage:
        extension = _extension(upload.filename)
        if extension not in self.settings.allowed_image_extensions:
            raise BusinessRuleViolation(
                "Unsupported image type",
                details={"allowed": sorted(self.settings.allowed_image_extensions)},
            )

        data = await upload.read(self.settings.MAX_UPLOAD_BYTES + 1)
        if len(data) > self.settings.MAX_UPLOAD_BYTES:
            raise PayloadTooLargeError(
                f"Image exceeds {self.settings.MAX_UPLOAD_BYTES} bytes",
                details={"max_bytes": self.settings.MAX_UPLOAD_BYTES},
            )
        if not data:
            raise BusinessRuleViolation("Uploaded file is empty")
        if not _looks_like_image(data, extension):
            raise BusinessRuleViolation("File content does not match its extension")

        relative = Path(prefix) / uuid.uuid4().hex[:2] / f"{uuid.uuid4().hex}.{extension}"
        absolute = self.root / relative
        absolute.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(absolute.write_bytes, data)
        logger.info(
            "image stored",
            extra={"ctx_path": str(relative), "ctx_size": len(data), "ctx_extension": extension},
        )
        url = f"/uploads/{relative.as_posix()}"
        if self.settings.PUBLIC_BASE_URL:
            url = self.settings.PUBLIC_BASE_URL.rstrip("/") + url
        return StoredImage(
            filename=absolute.name,
            url=url,
            size=len(data),
            content_type=upload.content_type or f"image/{extension}",
        )


class RemoteStorage:
    """Thin adapter for an internal upload gateway (S3/CDN in production).

    Disabled unless ``STORAGE_UPLOAD_URL`` is configured; pretending to upload
    (the old code returned a fabricated S3 URL) is worse than failing loudly.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.endpoint = getattr(settings, "STORAGE_UPLOAD_URL", "")

    async def save(self, upload: UploadFile, *, prefix: str = "items") -> StoredImage:
        if not self.endpoint:
            raise FeatureUnavailableError(
                "Remote storage is not configured (set STORAGE_UPLOAD_URL)"
            )
        raise FeatureUnavailableError("Remote storage adapter is not implemented in this build")


def build_storage(settings: Settings) -> StorageProvider:
    if settings.STORAGE_BACKEND == "cloud":
        return RemoteStorage(settings)
    return LocalStorage(settings)


def _looks_like_image(data: bytes, extension: str) -> bool:
    signatures = _IMAGE_MAGIC.get(extension, ())
    return any(data.startswith(signature) for signature in signatures)


__all__ = ["LocalStorage", "RemoteStorage", "StorageProvider", "StoredImage", "build_storage"]
