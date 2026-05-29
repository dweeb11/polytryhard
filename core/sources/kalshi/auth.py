from __future__ import annotations

import base64
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey


def _load_private_key(pem: str) -> RSAPrivateKey:
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
    if not hasattr(key, "sign"):
        raise ValueError("KALSHI_PRIVATE_KEY is not an RSA private key")
    return key  # type: ignore[return-value]


def sign_request(*, private_key_pem: str, method: str, path: str) -> tuple[str, str]:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    timestamp_ms = str(int(time.time() * 1000))
    sign_path = path.split("?", 1)[0]
    message = f"{timestamp_ms}{method.upper()}{sign_path}".encode()
    key = _load_private_key(private_key_pem)
    signature = key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return timestamp_ms, base64.b64encode(signature).decode("utf-8")


def auth_headers(*, key_id: str, private_key_pem: str, method: str, path: str) -> dict[str, str]:
    timestamp_ms, signature = sign_request(
        private_key_pem=private_key_pem,
        method=method,
        path=path,
    )
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "Accept": "application/json",
    }
