from __future__ import annotations

from moza.config import BackendConfig

from .base import BackendError, BackendUnauthorized, SecretNotFound, SecretsBackend
from .keychain import MacOSKeychainBackend

__all__ = [
    "BackendError",
    "BackendUnauthorized",
    "SecretNotFound",
    "SecretsBackend",
    "load_backend",
]


def load_backend(cfg: BackendConfig) -> SecretsBackend:
    if cfg.type == "macos_keychain":
        return MacOSKeychainBackend(service_prefix=cfg.options.get("service_prefix", "hat-"))
    if cfg.type == "gcp_secret_manager":
        from .gcp import GCPSecretManagerBackend
        return GCPSecretManagerBackend(project=cfg.options["project"])
    if cfg.type == "oci_vault":
        from .oci import OCIVaultBackend
        return OCIVaultBackend(
            vault_ocid=cfg.options["vault_ocid"],
            compartment_ocid=cfg.options["compartment_ocid"],
            region=cfg.options["region"],
        )
    raise ValueError(f"unknown backend type: {cfg.type}")
