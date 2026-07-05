from __future__ import annotations

import subprocess

from .base import BackendError, SecretNotFound, SecretsBackend


def _run(argv: list[str], stdin: bytes | None = None) -> tuple[int, bytes, bytes]:
    proc = subprocess.run(argv, input=stdin, capture_output=True, check=False)
    return proc.returncode, proc.stdout, proc.stderr


class MacOSKeychainBackend:
    def __init__(self, service_prefix: str = "moza-") -> None:
        self.service_prefix = service_prefix

    def get(self, ref: str) -> bytes:
        rc, out, err = _run(["security", "find-generic-password", "-w", "-s", ref])
        if rc == 44 or b"could not be found" in err:
            raise SecretNotFound(ref)
        if rc != 0:
            raise BackendError(err.decode("utf-8", "replace") or f"rc={rc}")
        return out.rstrip(b"\n")

    def put(self, name: str, value: bytes) -> str:
        rc, _, err = _run(
            ["security", "add-generic-password", "-U", "-s", name, "-a", name, "-w", value.decode("utf-8")]
        )
        if rc != 0:
            raise BackendError(err.decode("utf-8", "replace"))
        return name

    def delete(self, ref: str) -> None:
        rc, _, err = _run(["security", "delete-generic-password", "-s", ref])
        if rc == 44:
            raise SecretNotFound(ref)
        if rc != 0:
            raise BackendError(err.decode("utf-8", "replace"))

    def list(self, prefix: str | None = None) -> list[str]:
        return []

    def health_check(self) -> None:
        rc, _, err = _run(["security", "list-keychains"])
        if rc != 0:
            raise BackendError(err.decode("utf-8", "replace"))
