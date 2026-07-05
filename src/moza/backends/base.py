from __future__ import annotations

from typing import Protocol


class BackendError(Exception):
    pass


class SecretNotFound(BackendError):
    pass


class BackendUnauthorized(BackendError):
    pass


class SecretsBackend(Protocol):
    def get(self, ref: str) -> bytes: ...
    def put(self, name: str, value: bytes) -> str: ...
    def delete(self, ref: str) -> None: ...
    def list(self, prefix: str | None = None) -> list[str]: ...
    def health_check(self) -> None: ...
