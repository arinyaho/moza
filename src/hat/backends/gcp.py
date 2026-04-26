from __future__ import annotations

from google.api_core import exceptions as gex
from google.cloud.secretmanager import SecretManagerServiceClient

from .base import BackendError, BackendUnauthorized, SecretNotFound


class GCPSecretManagerBackend:
    def __init__(self, project: str) -> None:
        self.project = project
        self._client = SecretManagerServiceClient()

    def get(self, ref: str) -> bytes:
        try:
            resp = self._client.access_secret_version(request={"name": ref})
        except gex.NotFound as e:
            raise SecretNotFound(ref) from e
        except gex.PermissionDenied as e:
            raise BackendUnauthorized(str(e)) from e
        except gex.GoogleAPIError as e:
            raise BackendError(str(e)) from e
        return resp.payload.data

    def put(self, name: str, value: bytes) -> str:
        parent = f"projects/{self.project}"
        secret_path = f"{parent}/secrets/{name}"
        try:
            self._client.get_secret(request={"name": secret_path})
        except gex.NotFound:
            self._client.create_secret(
                request={
                    "parent": parent,
                    "secret_id": name,
                    "secret": {"replication": {"automatic": {}}},
                }
            )
        self._client.add_secret_version(
            request={"parent": secret_path, "payload": {"data": value}}
        )
        return f"{secret_path}/versions/latest"

    def delete(self, ref: str) -> None:
        secret_path = ref.rsplit("/versions/", 1)[0]
        try:
            self._client.delete_secret(request={"name": secret_path})
        except gex.NotFound as e:
            raise SecretNotFound(ref) from e
        except gex.PermissionDenied as e:
            raise BackendUnauthorized(str(e)) from e

    def list(self, prefix: str | None = None) -> list[str]:
        parent = f"projects/{self.project}"
        names = []
        for sec in self._client.list_secrets(request={"parent": parent}):
            short = sec.name.rsplit("/secrets/", 1)[-1]
            if prefix is None or short.startswith(prefix):
                names.append(f"{sec.name}/versions/latest")
        return names

    def health_check(self) -> None:
        try:
            list(self._client.list_secrets(request={"parent": f"projects/{self.project}"}))
        except gex.PermissionDenied as e:
            raise BackendUnauthorized(str(e)) from e
        except gex.GoogleAPIError as e:
            raise BackendError(str(e)) from e
