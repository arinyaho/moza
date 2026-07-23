from __future__ import annotations

from keyring.backends.macOS import Keyring as _MacKeyring
from keyring.errors import KeyringError, PasswordDeleteError

from .base import BackendError, SecretNotFound


class MacOSKeychainBackend:
    """Stores secrets in the macOS login Keychain.

    Uses the Security.framework binding (`keyring.backends.macOS`) directly rather
    than the `security(1)` CLI: `security add-generic-password -w <value>` puts
    the plaintext on the command line, where anything listing this user's
    processes can read it for the lifetime of the subprocess. The framework
    binding passes the value in-process, so it never reaches argv. This module
    deliberately does not import subprocess — that is a structural guarantee the
    secret cannot leak that way.

    The instance is created explicitly (not via keyring's global backend
    resolution) so this backend always means the macOS Keychain, regardless of
    any keyring configuration on the machine. The stored items are ordinary
    generic-password entries with service == account == the ref name, the same
    shape `security -s <ref> -a <ref>` produced, so items written by the previous
    CLI-based implementation remain readable.
    """

    def __init__(self, service_prefix: str = "mien-") -> None:
        self.service_prefix = service_prefix
        self._kc = _MacKeyring()

    def get(self, ref: str) -> bytes:
        try:
            value = self._kc.get_password(ref, ref)
        except KeyringError as e:
            raise BackendError(str(e)) from e
        if value is None:
            raise SecretNotFound(ref)
        return value.encode("utf-8")

    def put(self, name: str, value: bytes) -> str:
        try:
            self._kc.set_password(name, name, value.decode("utf-8"))
        except KeyringError as e:
            raise BackendError(str(e)) from e
        return name

    def delete(self, ref: str) -> None:
        try:
            self._kc.delete_password(ref, ref)
        except PasswordDeleteError as e:
            raise SecretNotFound(ref) from e
        except KeyringError as e:
            raise BackendError(str(e)) from e

    def list(self, prefix: str | None = None) -> list[str]:
        return []

    def health_check(self) -> None:
        # A read probe: reaches the Keychain without the write-time interaction
        # prompt, so it succeeds non-interactively when the store is available and
        # surfaces a real error when it is not.
        try:
            self._kc.get_password(f"{self.service_prefix}healthcheck", "probe")
        except KeyringError as e:
            raise BackendError(str(e)) from e
