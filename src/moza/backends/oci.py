from __future__ import annotations

import base64

import oci
from oci.exceptions import ServiceError
from oci.secrets import SecretsClient
from oci.vault import VaultsClient
from oci.vault.models import (
    Base64SecretContentDetails,
    CreateSecretDetails,
)

from .base import BackendError, BackendUnauthorized, SecretNotFound


class OCIVaultBackend:
    def __init__(
        self,
        vault_ocid: str,
        compartment_ocid: str,
        region: str,
        config_path: str = "~/.oci/config",
    ) -> None:
        self.vault_ocid = vault_ocid
        self.compartment_ocid = compartment_ocid
        self.region = region
        cfg = oci.config.from_file(file_location=config_path)
        cfg["region"] = region
        self._secrets = SecretsClient(cfg)
        self._vault = VaultsClient(cfg)

    def get(self, ref: str) -> bytes:
        try:
            resp = self._secrets.get_secret_bundle(secret_id=ref)
        except ServiceError as e:
            if e.status == 404:
                raise SecretNotFound(ref) from e
            if e.status in (401, 403):
                raise BackendUnauthorized(str(e)) from e
            raise BackendError(str(e)) from e
        encoded = resp.data.secret_bundle_content.content
        return base64.b64decode(encoded)

    def put(self, name: str, value: bytes) -> str:
        content = Base64SecretContentDetails(
            content=base64.b64encode(value).decode("ascii"),
        )
        details = CreateSecretDetails(
            compartment_id=self.compartment_ocid,
            vault_id=self.vault_ocid,
            secret_name=name,
            secret_content=content,
            key_id=None,
        )
        try:
            resp = self._vault.create_secret(create_secret_details=details)
        except ServiceError as e:
            if e.status in (401, 403):
                raise BackendUnauthorized(str(e)) from e
            raise BackendError(str(e)) from e
        return resp.data.id

    def delete(self, ref: str) -> None:
        try:
            self._vault.schedule_secret_deletion(
                secret_id=ref, schedule_secret_deletion_details={}
            )
        except ServiceError as e:
            if e.status == 404:
                raise SecretNotFound(ref) from e
            if e.status in (401, 403):
                raise BackendUnauthorized(str(e)) from e
            raise BackendError(str(e)) from e

    def list(self, prefix: str | None = None) -> list[str]:
        try:
            resp = self._vault.list_secrets(
                compartment_id=self.compartment_ocid, vault_id=self.vault_ocid
            )
        except ServiceError as e:
            if e.status in (401, 403):
                raise BackendUnauthorized(str(e)) from e
            raise BackendError(str(e)) from e
        names = []
        for s in resp.data:
            if prefix is None or s.secret_name.startswith(prefix):
                names.append(s.id)
        return names

    def health_check(self) -> None:
        self.list()
