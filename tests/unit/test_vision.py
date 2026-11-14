"""Vision service: lazy loading, validation and graceful degradation."""

from __future__ import annotations

import sys
from typing import Any

import pytest
from src.app.core.config import Settings
from src.app.core.exceptions import FeatureUnavailableError, ValidationError
from src.app.modules.items.vision import VisionService


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "ENVIRONMENT": "test",
        "SECRET_KEY": "x" * 48,
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "VISION_ENABLED": True,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


@pytest.mark.asyncio
async def test_disabled_vision_raises_feature_unavailable() -> None:
    service = VisionService(_settings(VISION_ENABLED=False))
    assert service.available is False

    with pytest.raises(FeatureUnavailableError, match="disabled"):
        await service.image_embedding(b"image")


@pytest.mark.asyncio
async def test_invalid_image_payloads_are_rejected() -> None:
    service = VisionService(_settings())
    with pytest.raises(ValidationError, match="empty"):
        await service.image_embedding(b"")
    with pytest.raises(ValidationError, match="too large"):
        await service.image_embedding(b"x" * (10 * 1024 * 1024 + 1))


@pytest.mark.asyncio
async def test_empty_text_is_rejected() -> None:
    service = VisionService(_settings())
    with pytest.raises(ValidationError, match="empty"):
        await service.text_embedding("   ")


@pytest.mark.asyncio
async def test_missing_model_raises_after_load_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    import types

    service = VisionService(_settings())

    class FailingModel:
        @classmethod
        def from_pretrained(cls, *args: object, **kwargs: object) -> Any:
            raise RuntimeError("boom")

    fake_torch = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False))
    fake_transformers = types.SimpleNamespace(
        ChineseCLIPModel=FailingModel,
        ChineseCLIPProcessor=types.SimpleNamespace(from_pretrained=lambda *_a, **_k: object()),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    with pytest.raises(FeatureUnavailableError, match="not available"):
        service._ensure_loaded()
    assert service._load_error == "boom"
    assert service.available is False
    with pytest.raises(FeatureUnavailableError, match="unavailable"):
        service._ensure_loaded()


@pytest.mark.asyncio
async def test_embeddings_delegate_to_the_thread_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    service = VisionService(_settings())
    monkeypatch.setattr(service, "_ensure_loaded", lambda: None)
    monkeypatch.setattr(service, "_image_embedding_sync", lambda _b: [0.1, 0.2])
    monkeypatch.setattr(service, "_text_embedding_sync", lambda _t: [0.3])
    monkeypatch.setattr(service, "_predict_tags_sync", lambda _b, _c: ["相机"])

    assert await service.image_embedding(b"image") == [0.1, 0.2]
    assert await service.text_embedding("相机") == [0.3]
    assert await service.predict_tags(b"image", ["相机", "手机"]) == ["相机"]


def test_require_model_and_normalise(monkeypatch: pytest.MonkeyPatch) -> None:
    service = VisionService(_settings())
    with pytest.raises(FeatureUnavailableError, match="not loaded"):
        service._require_model()

    class FakeTensor:
        def norm(self, *args: object, **kwargs: object) -> FakeTensor:
            return self

        def __truediv__(self, other: object) -> list[float]:
            return [1.0]

    class WithPooler:
        pooler_output = FakeTensor()

    class WithHidden:
        class _Hidden:
            def __getitem__(self, item: object) -> FakeTensor:
                return FakeTensor()

        last_hidden_state = _Hidden()

    assert VisionService._normalise(WithPooler()) == [1.0]
    assert VisionService._normalise(WithHidden()) == [1.0]
    assert VisionService._normalise(FakeTensor()) == [1.0]


def test_available_is_false_without_torch(monkeypatch: pytest.MonkeyPatch) -> None:
    service = VisionService(_settings())
    monkeypatch.setitem(sys.modules, "torch", None)
    assert service.available is False
