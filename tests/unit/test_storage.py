"""File storage: validation, magic bytes, local writes and remote stub."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from fastapi import UploadFile
from src.app.core.config import Settings
from src.app.core.exceptions import (
    BusinessRuleViolation,
    FeatureUnavailableError,
    PayloadTooLargeError,
)
from src.app.modules.items.storage import LocalStorage, RemoteStorage, build_storage

PNG = b"\x89PNG\r\n\x1a\n" + b"payload"


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "ENVIRONMENT": "test",
        "SECRET_KEY": "x" * 48,
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "UPLOAD_DIR": str(tmp_path),
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def _upload(data: bytes, filename: str = "photo.png") -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=filename)


@pytest.mark.asyncio
async def test_rejects_unsupported_extension(tmp_path: Path) -> None:
    storage = LocalStorage(_settings(tmp_path))
    with pytest.raises(BusinessRuleViolation, match="Unsupported"):
        await storage.save(_upload(PNG, "photo.exe"))


@pytest.mark.asyncio
async def test_rejects_oversize_empty_and_magic_mismatch(tmp_path: Path) -> None:
    storage = LocalStorage(_settings(tmp_path, MAX_UPLOAD_BYTES=1024))
    with pytest.raises(PayloadTooLargeError):
        await storage.save(_upload(PNG + b"x" * 1100))

    storage = LocalStorage(_settings(tmp_path))
    with pytest.raises(BusinessRuleViolation, match="empty"):
        await storage.save(_upload(b""))

    with pytest.raises(BusinessRuleViolation, match="does not match"):
        await storage.save(_upload(b"not-a-png", "photo.png"))


@pytest.mark.asyncio
async def test_saves_with_generated_name_and_public_url(tmp_path: Path) -> None:
    settings = _settings(tmp_path, PUBLIC_BASE_URL="https://cdn.example.test/")
    storage = LocalStorage(settings)
    stored = await storage.save(_upload(PNG, "My Photo.PNG"), prefix="items")

    assert stored.size == len(PNG)
    assert stored.content_type == "image/png"
    assert stored.url.startswith("https://cdn.example.test/uploads/items/")
    assert stored.filename.endswith(".png")
    assert (tmp_path / "items").exists()
    assert any((tmp_path / "items").rglob("*.png"))


@pytest.mark.asyncio
async def test_remote_storage_fails_loudly(tmp_path: Path) -> None:
    remote = RemoteStorage(_settings(tmp_path))
    with pytest.raises(FeatureUnavailableError, match="not configured"):
        await remote.save(_upload(PNG))

    assert isinstance(build_storage(_settings(tmp_path)), LocalStorage)
