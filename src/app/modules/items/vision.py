"""Lazy, async-friendly wrapper around the Chinese-CLIP vision model.

The previous module imported PyTorch + Transformers at import time, which meant
every API process downloaded/loaded ~600 MB *before serving traffic* (and tests
paid the same cost).  Here the model is loaded on first use, inside a lock, and
all inference runs in a worker thread so the event loop is never blocked.
"""

from __future__ import annotations

import asyncio
import io
import threading
from typing import Any

from src.app.core.config import Settings
from src.app.core.exceptions import FeatureUnavailableError, ValidationError
from src.app.core.logging import get_logger

logger = get_logger(__name__)


class VisionService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model: Any | None = None
        self._processor: Any | None = None
        self._device: str = "cpu"
        self._lock = threading.Lock()
        self._load_error: str | None = None

    # ------------------------------------------------------------- loading
    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        if not self.settings.VISION_ENABLED:
            raise FeatureUnavailableError("Vision features are disabled (VISION_ENABLED=false)")
        with self._lock:
            if self._model is not None:
                return
            if self._load_error is not None:
                raise FeatureUnavailableError(f"Vision model unavailable: {self._load_error}")
            try:
                import torch
                from transformers import ChineseCLIPModel, ChineseCLIPProcessor

                processor = ChineseCLIPProcessor.from_pretrained(self.settings.VISION_MODEL)
                model: Any = ChineseCLIPModel.from_pretrained(self.settings.VISION_MODEL)
                model.eval()
                device = "cuda" if torch.cuda.is_available() else "cpu"
                model.to(device)
                self._processor, self._model, self._device = processor, model, device
                logger.info(
                    "vision model loaded",
                    extra={"ctx_model": self.settings.VISION_MODEL, "ctx_device": device},
                )
            except Exception as exc:
                self._load_error = str(exc)[:300]
                logger.warning("vision model could not be loaded: %s", exc)
                raise FeatureUnavailableError(
                    "Vision model is not available in this deployment",
                    details={"reason": self._load_error},
                ) from exc

    # ----------------------------------------------------------- inference
    async def image_embedding(self, image_bytes: bytes) -> list[float]:
        self._validate_image(image_bytes)
        return await asyncio.wait_for(
            asyncio.to_thread(self._image_embedding_sync, image_bytes),
            timeout=self.settings.VISION_TIMEOUT_SECONDS,
        )

    async def text_embedding(self, text: str) -> list[float]:
        if not text.strip():
            raise ValidationError("Text must not be empty")
        return await asyncio.wait_for(
            asyncio.to_thread(self._text_embedding_sync, text),
            timeout=self.settings.VISION_TIMEOUT_SECONDS,
        )

    async def predict_tags(self, image_bytes: bytes, candidates: list[str]) -> list[str]:
        self._validate_image(image_bytes)
        return await asyncio.wait_for(
            asyncio.to_thread(self._predict_tags_sync, image_bytes, candidates),
            timeout=self.settings.VISION_TIMEOUT_SECONDS,
        )

    @property
    def available(self) -> bool:
        if not self.settings.VISION_ENABLED or self._load_error is not None:
            return False
        try:
            import torch  # noqa: F401  (capability probe)
            import transformers  # noqa: F401  (capability probe)
        except Exception:
            return False
        return True

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _validate_image(image_bytes: bytes) -> None:
        if not image_bytes:
            raise ValidationError("Image payload is empty")
        if len(image_bytes) > 10 * 1024 * 1024:
            raise ValidationError("Image payload is too large")

    def _image_embedding_sync(self, image_bytes: bytes) -> list[float]:
        self._ensure_loaded()
        processor, model = self._require_model()
        import torch
        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        inputs = processor(images=image, return_tensors="pt").to(self._device)
        with torch.no_grad():
            features = model.get_image_features(**inputs)
        features = self._normalise(features)
        return list(features.squeeze().cpu().tolist())

    def _text_embedding_sync(self, text: str) -> list[float]:
        self._ensure_loaded()
        processor, model = self._require_model()
        import torch

        inputs = processor(text=[text], padding=True, return_tensors="pt").to(self._device)
        with torch.no_grad():
            features = model.get_text_features(**inputs)
        features = self._normalise(features)
        return list(features.squeeze().cpu().tolist())

    def _predict_tags_sync(self, image_bytes: bytes, candidates: list[str]) -> list[str]:
        self._ensure_loaded()
        processor, model = self._require_model()
        import torch
        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        prompts = [f"一张{label}的照片" for label in candidates]
        image_inputs = processor(images=image, return_tensors="pt").to(self._device)
        text_inputs = processor(text=prompts, padding=True, return_tensors="pt").to(self._device)
        with torch.no_grad():
            image_features = self._normalise(model.get_image_features(**image_inputs))
            text_features = self._normalise(model.get_text_features(**text_inputs))
        logits = 100.0 * image_features @ text_features.T
        probabilities = logits.softmax(dim=1).cpu().numpy()[0]
        ranked = sorted(
            zip(candidates, probabilities, strict=True),
            key=lambda pair: pair[1],
            reverse=True,
        )
        return [label for label, probability in ranked[:2] if probability > 0.1]

    def _require_model(self) -> tuple[Any, Any]:
        """Narrow the optional attributes after ``_ensure_loaded`` for mypy."""

        if self._processor is None or self._model is None:
            raise FeatureUnavailableError("Vision model is not loaded")
        return self._processor, self._model

    @staticmethod
    def _normalise(features: Any) -> Any:
        # Some transformers versions return a model-output object instead of a tensor.
        if hasattr(features, "pooler_output"):
            features = features.pooler_output
        elif hasattr(features, "last_hidden_state"):
            features = features.last_hidden_state[:, 0, :]
        return features / features.norm(p=2, dim=-1, keepdim=True)


__all__ = ["VisionService"]
