import json
from pathlib import Path

import pytest

from hat.config import (
    BackendConfig,
    Config,
    GitHubService,
    GoogleService,
    Profile,
    SecretNaming,
    SlackWorkspace,
    config_path,
    load_config,
    save_config,
)


def test_config_path_uses_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("HAT_CONFIG", str(tmp_path / "custom.json"))
    assert config_path() == tmp_path / "custom.json"


def test_config_path_default(monkeypatch, tmp_path):
    monkeypatch.delenv("HAT_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert config_path() == tmp_path / ".config" / "hat" / "config.json"


def test_load_config_missing_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("HAT_CONFIG", str(tmp_path / "nope.json"))
    assert load_config() is None


def test_save_then_load_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("HAT_CONFIG", str(tmp_path / "c.json"))
    cfg = Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={"service_prefix": "hat-"}),
        bootstrap={},
        secret_naming=SecretNaming(
            default="hat-{profile}-{service}-{kind}",
            slack_token="hat-{profile}-slack-{workspace}-token",
        ),
        profiles={
            "personal": Profile(
                name="personal",
                google=GoogleService(
                    email="me@example.com",
                    oauth_client_id="cid",
                    oauth_client_secret_ref=None,
                    refresh_token_ref="hat-personal-google-refresh",
                    adc_ref=None,
                    gcloud_config_name="personal",
                    default_project=None,
                    gcloud_login_required=False,
                ),
                github=GitHubService(username="me", host="github.com", token_ref="hat-personal-github-token"),
                slack=[SlackWorkspace(workspace="team-a", team_id=None, user_token_ref="hat-personal-slack-team-a-token")],
            )
        },
    )
    save_config(cfg)
    loaded = load_config()
    assert loaded == cfg


def test_save_creates_parent_dir_and_chmods_600(monkeypatch, tmp_path):
    target = tmp_path / "deep" / "nested" / "config.json"
    monkeypatch.setenv("HAT_CONFIG", str(target))
    cfg = Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={},
        secret_naming=SecretNaming(default="x", slack_token="y"),
        profiles={},
    )
    save_config(cfg)
    assert target.exists()
    assert (target.stat().st_mode & 0o777) == 0o600


def test_load_rejects_unknown_schema_version(monkeypatch, tmp_path):
    p = tmp_path / "c.json"
    monkeypatch.setenv("HAT_CONFIG", str(p))
    p.write_text(json.dumps({"$schema_version": 99, "secrets_backend": {"type": "macos_keychain"}, "profiles": {}}))
    with pytest.raises(ValueError, match="schema_version"):
        load_config()
