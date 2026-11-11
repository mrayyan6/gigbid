"""Encrypted per-user OAuth token storage (Fernet, key from env TOKEN_ENCRYPTION_KEY).

Tokens are encrypted at rest, scoped by (user, provider), never logged and never shown by repr.
Generate a key with: python -c "from agent.security.tokens import new_key; print(new_key())"
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / "data" / "processed" / "tokens.enc.json"
_lock = threading.Lock()


class TokenError(Exception):
    """Missing key, wrong key or unknown user. The message never contains a token."""


def new_key() -> str:
    return Fernet.generate_key().decode()


def _fernet(key: str | None = None) -> Fernet:
    key = key or os.environ.get("TOKEN_ENCRYPTION_KEY", "")
    if not key:
        raise TokenError("TOKEN_ENCRYPTION_KEY is not set")
    try:
        return Fernet(key.encode())
    except ValueError as e:
        raise TokenError("TOKEN_ENCRYPTION_KEY is not a valid Fernet key") from e


def encrypt(plaintext: str, key: str | None = None) -> str:
    return _fernet(key).encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str, key: str | None = None) -> str:
    try:
        return _fernet(key).decrypt(ciphertext.encode()).decode()
    except InvalidToken as e:
        raise TokenError("cannot decrypt token (wrong key or corrupted data)") from e


class TokenStore:
    """JSON file of ciphertexts keyed by user then provider. Only ciphertext touches the disk."""

    def __init__(self, path: Path | str | None = None, key: str | None = None):
        self.path = Path(path) if path else DEFAULT_PATH
        self._key = key

    def __repr__(self) -> str:
        return f"TokenStore(path={self.path}, tokens=[hidden])"

    def _read(self) -> dict[str, dict[str, str]]:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def save(self, user: str, provider: str, token: dict | str) -> None:
        raw = token if isinstance(token, str) else json.dumps(token)
        with _lock:
            data = self._read()
            data.setdefault(user, {})[provider] = encrypt(raw, self._key)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data), encoding="utf-8")

    def load(self, user: str, provider: str) -> str:
        try:
            cipher = self._read()[user][provider]
        except KeyError as e:
            raise TokenError(f"no {provider} token stored for this user") from e
        return decrypt(cipher, self._key)

    def delete(self, user: str, provider: str) -> None:
        with _lock:
            data = self._read()
            if data.get(user, {}).pop(provider, None) is not None:
                self.path.write_text(json.dumps(data), encoding="utf-8")
