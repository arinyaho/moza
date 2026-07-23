from __future__ import annotations

import base64

import oci
from oci.exceptions import ServiceError
from oci.secrets import SecretsClient
from oci.vault import VaultsClient
from oci.vault.models import (
    Base64SecretContentDetails,
    CreateSecretDetails,
    UpdateSecretDetails,
)

from .base import BackendError, BackendUnauthorized, SecretNotFound

# Lifecycle states in which a secret can still be updated in place (possibly
# after cancelling a pending deletion). A DELETED secret is a tombstone and its
# name is free to reuse with a fresh create; CREATING/FAILED are transient and
# left to surface as a normal ServiceError rather than guessed at.
_UPDATABLE = {"ACTIVE", "UPDATING"}
_REACTIVATABLE = {"PENDING_DELETION", "SCHEDULING_DELETION", "CANCELLING_DELETION"}

# Cap on waiting for a cancelled deletion to return the secret to ACTIVE. The
# transition is normally seconds; this bounds a stuck one so `mien login` fails
# with a clear timeout rather than hanging.
_REACTIVATE_WAIT_SEC = 120


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
        """Create the secret, or add a new version if it already exists.

        A secret name is unique within a vault+compartment, so a plain
        create_secret fails once the name is taken — which is every push after
        the first, and is why the config manifest never used to update on OCI.
        This resolves the name to its OCID and updates in place instead, matching
        the GCP backend's upsert contract. A name left pending deletion by
        `logout` is reactivated first so a later `login` reuses it.
        """
        content = Base64SecretContentDetails(
            content=base64.b64encode(value).decode("ascii"),
        )
        existing = self._find_secret(name)
        try:
            if existing is not None:
                state = existing.lifecycle_state
                if state in _REACTIVATABLE:
                    # update_secret requires an ACTIVE secret, and cancellation
                    # is an async transition (the secret passes through
                    # CANCELLING_DELETION), so wait for ACTIVE before updating —
                    # otherwise the update races the cancel and 409s. A secret
                    # already cancelling must not be cancelled again (that itself
                    # 409s); it only needs the wait.
                    if state != "CANCELLING_DELETION":
                        self._vault.cancel_secret_deletion(secret_id=existing.id)
                    self._wait_active(existing.id)
                if state in _UPDATABLE or state in _REACTIVATABLE:
                    self._vault.update_secret(
                        secret_id=existing.id,
                        update_secret_details=UpdateSecretDetails(
                            secret_content=content
                        ),
                    )
                    return existing.id
                # Any other state (DELETED tombstone, etc.): fall through to create.
            details = CreateSecretDetails(
                compartment_id=self.compartment_ocid,
                vault_id=self.vault_ocid,
                secret_name=name,
                secret_content=content,
                key_id=None,
            )
            resp = self._vault.create_secret(create_secret_details=details)
        except ServiceError as e:
            if e.status in (401, 403):
                raise BackendUnauthorized(str(e)) from e
            raise BackendError(str(e)) from e
        return resp.data.id

    def _wait_active(self, secret_id: str) -> None:
        """Block until a secret reaches ACTIVE, so a subsequent update_secret is
        not rejected for a non-ACTIVE state. Bounded so a stuck transition fails
        loudly rather than hanging."""
        resp = self._vault.get_secret(secret_id=secret_id)
        oci.wait_until(
            self._vault, resp, "lifecycle_state", "ACTIVE",
            max_wait_seconds=_REACTIVATE_WAIT_SEC,
        )

    def _find_secret(self, name: str):
        """Return the live SecretSummary for an exact name, or None.

        A DELETED namesake is ignored — its name is free to reuse. Among any
        others (there is at most one non-deleted secret per name in a vault),
        the single match is returned.
        """
        try:
            resp = self._vault.list_secrets(
                compartment_id=self.compartment_ocid,
                vault_id=self.vault_ocid,
                name=name,
            )
        except ServiceError as e:
            if e.status in (401, 403):
                raise BackendUnauthorized(str(e)) from e
            raise BackendError(str(e)) from e
        for s in resp.data:
            if s.secret_name == name and s.lifecycle_state != "DELETED":
                return s
        return None

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
