""".. deprecated:: 0.2.0

Model allow-list policy moved to :mod:`src.app.core.config` (validated at start-up,
which is what actually prevents a misconfigured model from reaching production).
These helpers are kept for older scripts.
"""

from src.app.core.config import settings


def _parse_csv(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def get_proxy_api_key() -> str:
    key = settings.chat_api_key
    if not key:
        raise ValueError("Missing chat API key: set CHAT_API_KEY or API_KEY in .env")
    return key


def get_chat_base_url() -> str:
    return settings.CHAT_BASE_URL


def get_chat_model() -> str:
    model = settings.CHAT_MODEL
    if model not in _parse_csv(settings.ALLOWED_CHAT_MODELS):
        raise ValueError(f"Chat model not allowed: {model}")
    return model


def get_embedding_model() -> str:
    model = settings.ZHIPU_EMBEDDING_MODEL
    if model not in _parse_csv(settings.ALLOWED_EMBEDDING_MODELS):
        raise ValueError(f"Embedding model not allowed: {model}")
    return model


__all__ = [
    "get_chat_base_url",
    "get_chat_model",
    "get_embedding_model",
    "get_proxy_api_key",
]
