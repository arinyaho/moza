from __future__ import annotations

from moza.backends.base import SecretsBackend
from moza.config import BackendConfig, Config, deserialize_config, serialize_config

MANIFEST_SECRET_NAME = "moza-config-manifest"
_CLOUD_BACKENDS = {"gcp_secret_manager", "oci_vault"}


def is_cloud_backend(backend_cfg: BackendConfig) -> bool:
    return backend_cfg.type in _CLOUD_BACKENDS


def push_manifest(cfg: Config, backend: SecretsBackend) -> None:
    backend.put(MANIFEST_SECRET_NAME, serialize_config(cfg).encode("utf-8"))


def _ref_secret_name(ref: str) -> str | None:
    if "/secrets/" in ref:
        return ref.split("/secrets/", 1)[1].rsplit("/versions/", 1)[0]
    if ref.startswith("ref://"):
        return ref.removeprefix("ref://").rsplit("/versions/", 1)[0]
    return None


def pull_manifest(backend: SecretsBackend) -> Config | None:
    refs = backend.list(prefix=MANIFEST_SECRET_NAME)
    if not refs:
        return None
    exact = [r for r in refs if _ref_secret_name(r) == MANIFEST_SECRET_NAME]
    chosen = exact or refs  # OCI OCID refs aren't name-derivable -> keep prefix list
    data = backend.get(chosen[0])
    return deserialize_config(data.decode("utf-8"))
