from __future__ import annotations

from hat.backends.base import SecretsBackend
from hat.config import BackendConfig, Config, deserialize_config, serialize_config

MANIFEST_SECRET_NAME = "hat-config-manifest"
_CLOUD_BACKENDS = {"gcp_secret_manager", "oci_vault"}


def is_cloud_backend(backend_cfg: BackendConfig) -> bool:
    return backend_cfg.type in _CLOUD_BACKENDS


def push_manifest(cfg: Config, backend: SecretsBackend) -> None:
    backend.put(MANIFEST_SECRET_NAME, serialize_config(cfg).encode("utf-8"))


def pull_manifest(backend: SecretsBackend) -> Config | None:
    refs = backend.list(prefix=MANIFEST_SECRET_NAME)
    if not refs:
        return None
    data = backend.get(refs[0])
    return deserialize_config(data.decode("utf-8"))
