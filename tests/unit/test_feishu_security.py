"""Feishu signature verification and AES payload decryption."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7
from src.app.modules.feishu.security import FeishuCrypto

KEY = "test-feishu-encrypt-key"


def encrypt_payload(payload: dict[str, object], key: str = KEY) -> str:
    """Mirror Feishu's encryption so the decryptor is tested against real bytes."""

    plaintext = json.dumps(payload, ensure_ascii=False).encode()
    padder = PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    derived = hashlib.sha256(key.encode()).digest()
    iv = os.urandom(16)
    encryptor = Cipher(algorithms.AES(derived), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(iv + ciphertext).decode()


def sign(timestamp: str, nonce: str, body: bytes, key: str = KEY) -> str:
    material = timestamp.encode() + nonce.encode() + key.encode() + body
    return hashlib.sha256(material).hexdigest()


def test_signature_roundtrip_and_tamper_detection() -> None:
    crypto = FeishuCrypto(KEY)
    timestamp = str(int(time.time()))
    nonce = "abc123"
    body = b'{"token":"x"}'

    signature = sign(timestamp, nonce, body)
    assert crypto.verify(timestamp=timestamp, nonce=nonce, body=body, signature=signature)
    assert not crypto.verify(
        timestamp=timestamp, nonce=nonce, body=b'{"token":"y"}', signature=signature
    )
    assert not crypto.verify(timestamp=timestamp, nonce=nonce, body=body, signature="bad")


def test_stale_timestamp_is_rejected() -> None:
    crypto = FeishuCrypto(KEY, max_skew_seconds=60)
    timestamp = str(int(time.time()) - 600)
    body = b"{}"
    assert not crypto.verify(
        timestamp=timestamp,
        nonce="n",
        body=body,
        signature=sign(timestamp, "n", body),
    )


def test_decrypts_encrypted_body() -> None:
    crypto = FeishuCrypto(KEY)
    original = {"type": "url_verification", "challenge": "ch-1", "token": "t"}
    body = json.dumps({"encrypt": encrypt_payload(original)}).encode()

    assert crypto.decode(body) == original


def test_plain_body_is_passed_through() -> None:
    crypto = FeishuCrypto(KEY)
    payload = {"type": "event_callback", "token": "t"}
    assert crypto.decode(json.dumps(payload).encode()) == payload


def test_unconfigured_crypto_skips_signature_but_rejects_ciphertext() -> None:
    crypto = FeishuCrypto("")
    assert not crypto.configured
    assert crypto.verify(timestamp="", nonce="", body=b"{}", signature="")

    encrypted = json.dumps({"encrypt": encrypt_payload({}, key="whatever")}).encode()
    with pytest.raises(PermissionError):
        crypto.decode(encrypted)


def test_plain_body_with_unconfigured_crypto() -> None:
    crypto = FeishuCrypto("")
    assert crypto.decode(b'{"challenge":"x"}') == {"challenge": "x"}


def test_invalid_base64_is_rejected() -> None:
    crypto = FeishuCrypto(KEY)
    with pytest.raises(ValueError):
        crypto.decode(b'{"encrypt":"not-base64!!!"}')
