import pytest

from hat.config import BackendConfig, Config, GitHubService, Profile, SecretNaming
from hat.manifest import (
    MANIFEST_SECRET_NAME,
    is_cloud_backend,
    pull_manifest,
    push_manifest,
)


class FakeBackend:
    def __init__(self):
        self.store: dict[str, bytes] = {}

    def put(self, name: str, value: bytes) -> str:
        self.store[name] = value
        return f"ref://{name}/versions/latest"

    def get(self, ref: str) -> bytes:
        name = ref.removeprefix("ref://").rsplit("/versions/", 1)[0]
        return self.store[name]

    def list(self, prefix: str | None = None) -> list[str]:
        return [
            f"ref://{n}/versions/latest"
            for n in self.store
            if prefix is None or n.startswith(prefix)
        ]


def _cfg(type_="gcp_secret_manager") -> Config:
    return Config(
        schema_version=1,
        secrets_backend=BackendConfig(type=type_, options={"project": "p1"}),
        bootstrap={"gcp_account": "me@x.com"},
        secret_naming=SecretNaming(
            default="hat-{profile}-{service}-{kind}",
            slack_token="hat-{profile}-slack-{workspace}-token",
        ),
        profiles={"work": Profile(name="work",
                                  github=GitHubService(username="u", host="github.com",
                                                       token_ref="ref://gh"))},
    )


def test_is_cloud_backend():
    assert is_cloud_backend(BackendConfig(type="gcp_secret_manager", options={}))
    assert is_cloud_backend(BackendConfig(type="oci_vault", options={}))
    assert not is_cloud_backend(BackendConfig(type="macos_keychain", options={}))


def test_push_then_pull_roundtrips():
    b = FakeBackend()
    push_manifest(_cfg(), b)
    assert MANIFEST_SECRET_NAME in b.store
    restored = pull_manifest(b)
    assert restored is not None
    assert restored.profiles["work"].github.token_ref == "ref://gh"


def test_pull_returns_none_when_absent():
    assert pull_manifest(FakeBackend()) is None


def test_pull_raises_on_bad_schema_version():
    b = FakeBackend()
    b.store[MANIFEST_SECRET_NAME] = b'{"$schema_version": 99, "secrets_backend": {"type": "macos_keychain"}, "bootstrap": {}, "secret_naming": {}, "profiles": {}}'
    with pytest.raises(ValueError, match="schema_version"):
        pull_manifest(b)
