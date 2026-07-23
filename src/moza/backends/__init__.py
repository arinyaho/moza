from __future__ import annotations

from moza.config import BackendConfig

from .base import BackendError, BackendUnauthorized, SecretNotFound, SecretsBackend

__all__ = [
    "BackendError",
    "BackendUnauthorized",
    "SecretNotFound",
    "SecretsBackend",
    "load_backend",
]


def load_backend(cfg: BackendConfig) -> SecretsBackend:
    if cfg.type == "macos_keychain":
        # Imported lazily: keychain.py binds keyring.backends.macOS at module
        # level, which is macOS-only. A Linux user on the keyring backend must be
        # able to load_backend without dragging that in.
        from .keychain import MacOSKeychainBackend
        return MacOSKeychainBackend(service_prefix=cfg.options.get("service_prefix", "moza-"))
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
    if cfg.type == "keyring":
        from .keyring_store import KeyringBackend
        return KeyringBackend(service_prefix=cfg.options.get("service_prefix", "moza-"))
    raise ValueError(f"unknown backend type: {cfg.type}")
