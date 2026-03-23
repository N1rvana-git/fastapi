from pydantic import BaseModel
from typing import Any, Dict

class FeishuWebhookPayload(BaseModel):
    challenge: str | None = None
    type: str | None = None
    token: str | None = None
    header: Dict[str, Any] | None = None
    event: Dict[str, Any] | None = None
