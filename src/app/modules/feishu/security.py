"""Feishu event authenticity: signature verification + AES decryption.

Feishu can be configured with an ``Encrypt Key``:

* every callback carries ``X-Lark-Request-Timestamp`` / ``-Nonce`` /
  ``-Signature``; the signature is ``sha256(timestamp + nonce + encrypt_key + body)``;
* the JSON body is then ``{"encrypt": "<base64>"}``, an AES-256-CBC ciphertext
  whose key is ``sha256(encrypt_key)`` and whose IV is the first 16 bytes of the
  decoded payload (PKCS#7 padding).

Without this, anybody who learns the webhook URL can forge user messages.
The verification token remains as a second, cheap check.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from hmac import compare_digest

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from src.app.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_MAX_SKEW_SECONDS = 300


class FeishuCrypto:
    def __init__(
        self, encrypt_key: str, *, max_skew_seconds: int = DEFAULT_MAX_SKEW_SECONDS
    ) -> None:
        self.encrypt_key = encrypt_key.strip()
        self.max_skew_seconds = max_skew_seconds

    @property
    def configured(self) -> bool:
        return bool(self.encrypt_key)

    # ------------------------------------------------------------- signature
    def signature(self, timestamp: str, nonce: str, body: bytes) -> str:
        if not self.configured:
            return ""
        material = timestamp.encode() + nonce.encode() + self.encrypt_key.encode() + body
        return hashlib.sha256(material).hexdigest()

    def verify(self, *, timestamp: str, nonce: str, body: bytes, signature: str) -> bool:
        """Verify signature and freshness. Returns True when not configured."""

        if not self.configured:
            return True
        if not timestamp or not nonce or not signature:
            return False
        if not self._is_fresh(timestamp):
            return False
        expected = self.signature(timestamp, nonce, body)
        return compare_digest(expected, signature)

    # -------------------------------------------------------------- payload
    def decode(self, body: bytes) -> dict[str, object]:
        """Parse a plaintext or encrypted callback body."""

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid JSON payload") from exc
        if not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")
        encrypted = payload.get("encrypt")
        if not encrypted:
            return payload
        if not self.configured:
            raise PermissionError("encrypted event received but FEISHU_ENCRYPT_KEY is not set")
        if not isinstance(encrypted, str):
            raise ValueError("encrypt field must be a string")
        return self._decrypt_payload(encrypted)

    def _decrypt_payload(self, encrypted: str) -> dict[str, object]:
        try:
            blob = base64.b64decode(encrypted, validate=True)
        except Exception as exc:
            raise ValueError("encrypt field is not valid base64") from exc
        if len(blob) <= 16:
            raise ValueError("encrypted payload is too short")

        key = hashlib.sha256(self.encrypt_key.encode()).digest()
        iv, ciphertext = blob[:16], blob[16:]
        decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = PKCS7(128).unpadder()
        try:
            plaintext = unpadder.update(padded) + unpadder.finalize()
        except ValueError as exc:
            raise ValueError("invalid padding: wrong encrypt key?") from exc

        try:
            decoded = json.loads(plaintext)
        except json.JSONDecodeError as exc:
            raise ValueError("decrypted payload is not JSON") from exc
        if not isinstance(decoded, dict):
            raise ValueError("decrypted payload must be a JSON object")
        return decoded

    def _is_fresh(self, timestamp: str) -> bool:
        try:
            sent_at = int(timestamp)
        except (TypeError, ValueError):
            return False
        return abs(time.time() - sent_at) <= self.max_skew_seconds


__all__ = ["DEFAULT_MAX_SKEW_SECONDS", "FeishuCrypto"]
