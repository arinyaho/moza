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


def test_use_emits_exports(runner, hat_cfg, mocker):
    runner.invoke(main, ["init"], input="3\nhat-\n")
    backend = mocker.patch("hat.cli.load_backend").return_value
    backend.put.return_value = "ref://gh"
    runner.invoke(main, ["login", "personal", "--service", "github"], input="me\nghp_xxx\n")

    backend.get.return_value = b"ghp_xxx"
    result = runner.invoke(main, ["use", "personal"])
    assert result.exit_code == 0
    assert "export HAT_PROFILE='personal'" in result.output
    assert "export GH_TOKEN='ghp_xxx'" in result.output


def test_unset_emits_unsets(runner, hat_cfg):
    runner.invoke(main, ["init"], input="3\nhat-\n")
    result = runner.invoke(main, ["unset"])
    assert "unset HAT_PROFILE" in result.output


def test_token_google_prints_access_token(runner, hat_cfg, mocker):
    runner.invoke(main, ["init"], input="3\nhat-\n")
    backend = mocker.patch("hat.cli.load_backend").return_value
    backend.put.side_effect = ["ref://oauth", "ref://refresh"]
    backend.get.side_effect = lambda r: {
        "ref://oauth": b"csec",
        "ref://refresh": b"refresh-zzz",
    }[r]
    mocker.patch("hat.cli.google_installed_app_flow", return_value="refresh-zzz")
    mocker.patch("hat.cli.exchange_refresh_token", return_value="ya29-access")

    runner.invoke(
        main,
        ["login", "personal", "--service", "google",
         "--email", "me@x.com", "--client-id", "cid"],
        input="csec\n",
    )

    result = runner.invoke(main, ["token", "google"], env={"HAT_PROFILE": "personal", "HAT_CONFIG": str(hat_cfg)})
    assert result.exit_code == 0
    assert "ya29-access" in result.output


def test_logout_removes_service(runner, hat_cfg, mocker):
    backend = mocker.patch("hat.cli.load_backend").return_value
    backend.put.return_value = "ref://gh"
    runner.invoke(main, ["init"], input="3\nhat-\n")
    runner.invoke(main, ["login", "personal", "--service", "github"], input="me\ntok\n")
    result = runner.invoke(main, ["logout", "personal", "--service", "github"])
    assert result.exit_code == 0
    backend.delete.assert_called_with("ref://gh")
    payload = json.loads(hat_cfg.read_text())
    assert payload["profiles"]["personal"]["github"] is None


def test_doctor_runs_health_check(runner, hat_cfg, mocker):
    runner.invoke(main, ["init"], input="3\nhat-\n")
    backend = mocker.patch("hat.cli.load_backend").return_value
    result = runner.invoke(main, ["doctor"])
    assert result.exit_code == 0
    backend.health_check.assert_called_once()
    assert "OK" in result.output


def test_doctor_reports_failure(runner, hat_cfg, mocker):
    runner.invoke(main, ["init"], input="3\nhat-\n")
    backend = mocker.patch("hat.cli.load_backend").return_value
    backend.health_check.side_effect = RuntimeError("boom")
    result = runner.invoke(main, ["doctor"])
    assert result.exit_code != 0
    assert "boom" in result.output


def test_doctor_gc_sweeps(runner, hat_cfg, mocker):
    runner.invoke(main, ["init"], input="3\nhat-\n")
    mocker.patch("hat.cli.load_backend").return_value
    gc = mocker.patch("hat.cli.EphemeralStore.gc")
    runner.invoke(main, ["doctor", "--gc"])
    gc.assert_called_once()


def test_init_rejects_project_name_with_space(runner, hat_cfg):
    result = runner.invoke(main, ["init"], input="1\nMy First Project\n")
    assert result.exit_code != 0
    assert "PROJECT_ID" in result.output
    assert "gcloud projects list" in result.output
    assert not hat_cfg.exists()


def test_init_rejects_uppercase_project_id(runner, hat_cfg):
    result = runner.invoke(main, ["init"], input="1\nMy-Project\n")
    assert result.exit_code != 0
    assert "PROJECT_ID" in result.output


def test_init_strips_markdown_email(runner, hat_cfg, mocker):
    backend = mocker.patch("hat.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("hat.cli.subprocess.run")  # don't touch real gcloud ADC
    result = runner.invoke(
        main,
        ["init"],
        input="1\nmy-proj-1\n[a@b.com](mailto:a@b.com)\n",
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(hat_cfg.read_text())
    assert payload["bootstrap"]["gcp_account"] == "a@b.com"


def test_init_aborts_on_health_check_failure_with_actionable_message(runner, hat_cfg, mocker):
    backend = mocker.patch("hat.cli.load_backend").return_value
    backend.health_check.side_effect = RuntimeError("permission denied: caller lacks role")
    result = runner.invoke(main, ["init"], input="1\nmy-proj-1\nme@x.com\n")
    assert result.exit_code != 0
    out = result.output
    assert "permission denied" in out.lower()
    assert "gcloud auth application-default login --account=me@x.com" in out
    assert "hat doctor" in out
    # Config should still be on disk so user can fix without re-prompting.
    assert hat_cfg.exists()


def test_init_keychain_runs_health_check(runner, hat_cfg, mocker):
    backend = mocker.patch("hat.cli.load_backend").return_value
    backend.health_check.return_value = None
    result = runner.invoke(main, ["init"], input="3\nhat-\n")
    assert result.exit_code == 0
    backend.health_check.assert_called_once()
    assert "OK" in result.output


def test_init_sets_quota_project_for_gcp(runner, hat_cfg, mocker):
    backend = mocker.patch("hat.cli.load_backend").return_value
    backend.health_check.return_value = None
    sub = mocker.patch("hat.cli.subprocess.run")
    result = runner.invoke(main, ["init"], input="1\nsayu-studio\nme@x.com\n")
    assert result.exit_code == 0, result.output
    quota_calls = [
        c for c in sub.call_args_list
        if c[0][0][:4] == ["gcloud", "auth", "application-default", "set-quota-project"]
    ]
    assert len(quota_calls) == 1
    assert quota_calls[0][0][0][4] == "sayu-studio"
    assert "quota project to sayu-studio" in result.output


def test_init_warns_when_quota_project_set_fails(runner, hat_cfg, mocker):
    backend = mocker.patch("hat.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("hat.cli.subprocess.run", side_effect=FileNotFoundError("gcloud"))
    result = runner.invoke(main, ["init"], input="1\nsayu-studio\nme@x.com\n")
    assert result.exit_code == 0
    assert "could not set ADC quota project" in result.output
    assert "gcloud auth application-default set-quota-project sayu-studio" in result.output


def test_login_google_shows_oauth_hint_when_client_id_missing(runner, hat_cfg, mocker):
    backend = mocker.patch("hat.cli.load_backend").return_value
    backend.health_check.return_value = None
    backend.put.side_effect = ["ref://oauth", "ref://refresh"]
    mocker.patch("hat.cli.google_installed_app_flow", return_value="refresh-zzz")
    mocker.patch("hat.cli.subprocess.run")  # set-quota-project no-op
    runner.invoke(main, ["init"], input="1\nsayu-studio\nme@x.com\n")
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "google", "--email", "me@x.com"],
        input="my-cid\nmy-csec\n",
    )
    assert result.exit_code == 0, result.output
    assert "OAuth Desktop client" in result.output
    assert "console.cloud.google.com/apis/credentials" in result.output
    assert "sayu-studio" in result.output


def test_login_google_skips_hint_when_client_id_provided(runner, hat_cfg, mocker):
    backend = mocker.patch("hat.cli.load_backend").return_value
    backend.health_check.return_value = None
    backend.put.side_effect = ["ref://oauth", "ref://refresh"]
    mocker.patch("hat.cli.google_installed_app_flow", return_value="refresh-zzz")
    mocker.patch("hat.cli.subprocess.run")
    runner.invoke(main, ["init"], input="1\nsayu-studio\nme@x.com\n")
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "google",
         "--email", "me@x.com", "--client-id", "cid"],
        input="csec\n",
    )
    assert result.exit_code == 0, result.output
    assert "OAuth Desktop client" not in result.output
