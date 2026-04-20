from src.config import settings


def _parse_csv(value: str) -> set[str]:
    return {v.strip() for v in value.split(",") if v.strip()}


def get_proxy_api_key() -> str:
    key = settings.CHAT_API_KEY or settings.API_KEY or settings.API_KEy
    if not key:
        raise ValueError("Missing chat API key: set CHAT_API_KEY or API_KEY in .env")
    return key


def get_chat_base_url() -> str:
    return settings.CHAT_BASE_URL


def get_chat_model() -> str:
    model = settings.CHAT_MODEL
    allowed = _parse_csv(settings.ALLOWED_CHAT_MODELS)
    if model not in allowed:
        raise ValueError(f"Chat model not allowed: {model}. Allowed: {sorted(allowed)}")
    return model


def get_embedding_model() -> str:
    model = settings.ZHIPU_EMBEDDING_MODEL
    allowed = _parse_csv(settings.ALLOWED_EMBEDDING_MODELS)
    if model not in allowed:
        raise ValueError(f"Embedding model not allowed: {model}. Allowed: {sorted(allowed)}")
    return model
