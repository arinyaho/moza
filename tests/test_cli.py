import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from hat.cli import main


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def hat_cfg(monkeypatch, tmp_path):
    p = tmp_path / "hat.json"
    monkeypatch.setenv("HAT_CONFIG", str(p))
    return p


def test_list_no_config(runner, hat_cfg):
    result = runner.invoke(main, ["list"])
    assert result.exit_code != 0
    assert "hat init" in result.output


def test_status_when_unset(runner, hat_cfg, monkeypatch):
    monkeypatch.delenv("HAT_PROFILE", raising=False)
    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0
    assert "no profile active" in result.output.lower()


def test_status_active(runner, hat_cfg, monkeypatch):
    monkeypatch.setenv("HAT_PROFILE", "personal")
    result = runner.invoke(main, ["status"])
    assert "personal" in result.output


def test_init_writes_keychain_skeleton(runner, hat_cfg):
    result = runner.invoke(main, ["init"], input="3\nhat-\n")
    assert result.exit_code == 0, result.output
    payload = json.loads(hat_cfg.read_text())
    assert payload["secrets_backend"]["type"] == "macos_keychain"
    assert payload["profiles"] == {}


def test_list_after_init(runner, hat_cfg):
    runner.invoke(main, ["init"], input="3\nhat-\n")
    result = runner.invoke(main, ["list"])
    assert result.exit_code == 0
    assert "no profiles" in result.output.lower()


def test_whoami_unknown_profile(runner, hat_cfg):
    runner.invoke(main, ["init"], input="3\nhat-\n")
    result = runner.invoke(main, ["whoami", "nope"])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_login_github_stores_token_and_updates_config(runner, hat_cfg, mocker):
    mocker.patch("hat.cli.load_backend").return_value.put.return_value = "ref://gh-token"
    runner.invoke(main, ["init"], input="3\nhat-\n")
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "github"],
        input="myuser\nghp_token123\n",
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(hat_cfg.read_text())
    gh = payload["profiles"]["personal"]["github"]
    assert gh["username"] == "myuser"
    assert gh["host"] == "github.com"
    assert gh["token_ref"] == "ref://gh-token"


def test_login_slack_requires_workspace(runner, hat_cfg):
    runner.invoke(main, ["init"], input="3\nhat-\n")
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "slack"],
    )
    assert result.exit_code != 0
    assert "--workspace" in result.output


def test_login_slack_appends_workspace(runner, hat_cfg, mocker):
    mocker.patch("hat.cli.load_backend").return_value.put.side_effect = [
        "ref://slack-a",
        "ref://slack-b",
    ]
    runner.invoke(main, ["init"], input="3\nhat-\n")
    runner.invoke(main, ["login", "personal", "--service", "slack", "--workspace", "team-a"], input="xoxp-aaa\n")
    runner.invoke(main, ["login", "personal", "--service", "slack", "--workspace", "team-b"], input="xoxp-bbb\n")
    payload = json.loads(hat_cfg.read_text())
    workspaces = payload["profiles"]["personal"]["slack"]
    assert [w["workspace"] for w in workspaces] == ["team-a", "team-b"]
    assert workspaces[0]["user_token_ref"] == "ref://slack-a"


def test_login_google_runs_oauth_and_stores(runner, hat_cfg, mocker):
    mocker.patch("hat.cli.google_installed_app_flow", return_value="refresh-zzz")
    backend = mocker.patch("hat.cli.load_backend").return_value
    backend.put.side_effect = [
        "ref://oauth-secret",
        "ref://refresh",
    ]
    runner.invoke(main, ["init"], input="3\nhat-\n")
    result = runner.invoke(
        main,
        [
            "login", "personal", "--service", "google",
            "--email", "me@example.com",
            "--client-id", "cid",
        ],
        input="csec\n",
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(hat_cfg.read_text())
    g = payload["profiles"]["personal"]["google"]
    assert g["email"] == "me@example.com"
    assert g["oauth_client_id"] == "cid"
    assert g["refresh_token_ref"] == "ref://refresh"
    assert g["oauth_client_secret_ref"] == "ref://oauth-secret"
    assert g["gcloud_config_name"] == "personal"
