import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from core.sources.kalshi.auth import auth_headers, sign_request

TEST_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
TEST_PEM = TEST_KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode("utf-8")


def test_sign_request_uses_stable_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.sources.kalshi.auth.time.time", lambda: 1_700_000_000.0)
    ts1, sig1 = sign_request(private_key_pem=TEST_PEM, method="GET", path="/trade-api/v2/markets")
    ts2, sig2 = sign_request(private_key_pem=TEST_PEM, method="GET", path="/trade-api/v2/markets")
    assert ts1 == ts2 == "1700000000000"
    assert sig1
    assert sig2


def test_auth_headers_include_kalshi_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.sources.kalshi.auth.time.time", lambda: 1_700_000_000.0)
    headers = auth_headers(
        key_id="test-key",
        private_key_pem=TEST_PEM,
        method="GET",
        path="/trade-api/v2/markets",
    )
    assert headers["KALSHI-ACCESS-KEY"] == "test-key"
    assert headers["KALSHI-ACCESS-TIMESTAMP"]
    assert headers["KALSHI-ACCESS-SIGNATURE"]
