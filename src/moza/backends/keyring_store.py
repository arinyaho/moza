from __future__ import annotations

import keyring
from keyring.errors import PasswordDeleteError

from .base import BackendError, SecretNotFound


class KeyringBackend:
    def __init__(self, service_prefix: str = "moza-") -> None:
        self.service_prefix = service_prefix

    def get(self, ref: str) -> bytes:
        value = keyring.get_password(ref, ref)
        if value is None:
            raise SecretNotFound(ref)
        return value.encode("utf-8")

    def put(self, name: str, value: bytes) -> str:
        keyring.set_password(name, name, value.decode("utf-8"))
        return name

    def delete(self, ref: str) -> None:
        try:
            keyring.delete_password(ref, ref)
        except PasswordDeleteError as e:
            raise SecretNotFound(ref) from e

    def list(self, prefix: str | None = None) -> list[str]:
        return []

    def health_check(self) -> None:
        kr = keyring.get_keyring()
        if isinstance(kr, keyring.backends.fail.Keyring):
            raise BackendError(
                "no usable keyring backend available"
                " (needs a Secret Service / desktop session; not available on headless systems)"
            )
        try:
            keyring.get_password(f"{self.service_prefix}healthcheck", "probe")
        except Exception as e:
            raise BackendError(str(e)) from e
