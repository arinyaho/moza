import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from moza.cli import main


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def moza_cfg(monkeypatch, tmp_path):
    p = tmp_path / "moza.json"
    monkeypatch.setenv("MOZA_CONFIG", str(p))
    return p


def test_list_no_config(runner, moza_cfg):
    result = runner.invoke(main, ["list"])
    assert result.exit_code != 0
    assert "moza init" in result.output


def test_status_when_unset(runner, moza_cfg, monkeypatch):
    monkeypatch.delenv("MOZA_PROFILE", raising=False)
    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0
    assert "no profile active" in result.output.lower()


def test_status_active(runner, moza_cfg, monkeypatch):
    monkeypatch.setenv("MOZA_PROFILE", "personal")
    result = runner.invoke(main, ["status"])
    assert "personal" in result.output


def test_init_writes_keychain_skeleton(runner, moza_cfg):
    result = runner.invoke(main, ["init"], input="3\nmoza-\n")
    assert result.exit_code == 0, result.output
    payload = json.loads(moza_cfg.read_text())
    assert payload["secrets_backend"]["type"] == "macos_keychain"
    assert payload["profiles"] == {}


def test_list_after_init(runner, moza_cfg):
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    result = runner.invoke(main, ["list"])
    assert result.exit_code == 0
    assert "no profiles" in result.output.lower()


def test_whoami_unknown_profile(runner, moza_cfg):
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    result = runner.invoke(main, ["whoami", "nope"])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_login_github_stores_token_and_updates_config(runner, moza_cfg, mocker):
    mocker.patch("moza.cli.load_backend").return_value.put.return_value = "ref://gh-token"
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "github"],
        input="y\nmyuser\nghp_token123\nn\n",
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(moza_cfg.read_text())
    gh = payload["profiles"]["personal"]["github"]
    assert gh["username"] == "myuser"
    assert gh["host"] == "github.com"
    assert gh["token_ref"] == "ref://gh-token"


def test_login_slack_requires_workspace(runner, moza_cfg):
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "slack"],
        input="y\n",
    )
    assert result.exit_code != 0
    assert "--workspace" in result.output


def test_login_slack_appends_workspace(runner, moza_cfg, mocker):
    mocker.patch("moza.cli.load_backend").return_value.put.side_effect = [
        "ref://slack-a",
        "ref://slack-b",
    ]
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    runner.invoke(main, ["login", "personal", "--service", "slack", "--workspace", "team-a"], input="y\nxoxp-aaa\n")
    runner.invoke(main, ["login", "personal", "--service", "slack", "--workspace", "team-b"], input="xoxp-bbb\n")
    payload = json.loads(moza_cfg.read_text())
    workspaces = payload["profiles"]["personal"]["slack"]
    assert [w["workspace"] for w in workspaces] == ["team-a", "team-b"]
    assert workspaces[0]["user_token_ref"] == "ref://slack-a"


def test_login_google_runs_oauth_and_stores(runner, moza_cfg, mocker):
    mocker.patch("moza.cli.google_installed_app_flow", return_value="refresh-zzz")
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.put.side_effect = [
        "ref://oauth-secret",
        "ref://refresh",
    ]
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    result = runner.invoke(
        main,
        [
            "login", "personal", "--service", "google",
            "--email", "me@example.com",
            "--client-id", "cid",
        ],
        input="y\ncsec\n",
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(moza_cfg.read_text())
    g = payload["profiles"]["personal"]["google"]
    assert g["email"] == "me@example.com"
    assert g["oauth_client_id"] == "cid"
    assert g["refresh_token_ref"] == "ref://refresh"
    assert g["oauth_client_secret_ref"] == "ref://oauth-secret"
    assert g["gcloud_config_name"] == "personal"


def test_use_routes_secrets_through_ephemeral_file(runner, moza_cfg, mocker, tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.put.return_value = "ref://gh"
    runner.invoke(main, ["login", "personal", "--service", "github"], input="y\nme\nghp_xxx\nn\n")

    backend.get.return_value = b"ghp_xxx"
    result = runner.invoke(main, ["use", "personal"])
    assert result.exit_code == 0, result.output

    # Token must never appear on stdout: that was the original leak vector
    # (caller forgets `eval`, stdout lands in transcript / shell history / ps).
    assert "ghp_xxx" not in result.output

    # Output is a one-liner that sources a path under TMPDIR/moza and rm's it.
    import re
    m = re.match(r"\. '([^']+)' && rm -f '\1'", result.output.strip())
    assert m, result.output
    script = Path(m.group(1))
    body = script.read_text()
    assert "export MOZA_PROFILE='personal'" in body
    assert "export GH_TOKEN='ghp_xxx'" in body


def test_use_refuses_when_stdout_is_a_tty(runner, moza_cfg, mocker, monkeypatch):
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.put.return_value = "ref://gh"
    runner.invoke(main, ["login", "personal", "--service", "github"], input="y\nme\nghp_xxx\nn\n")

    # Force the TTY heuristic on Click's StringIO so we can test the guard.
    mocker.patch("moza.cli._stdout_is_tty", return_value=True)
    result = runner.invoke(main, ["use", "personal"])

    # Must exit non-zero with a hint at the wrapper / eval form. Crucially,
    # the secret must NOT have been resolved or printed.
    assert result.exit_code != 0
    assert "ghp_xxx" not in result.output
    assert "eval" in result.output or "moza-use" in result.output


def test_use_print_flag_overrides_tty_guard(runner, moza_cfg, mocker, tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.put.return_value = "ref://gh"
    runner.invoke(main, ["login", "personal", "--service", "github"], input="y\nme\nghp_xxx\nn\n")

    backend.get.return_value = b"ghp_xxx"
    mocker.patch("moza.cli._stdout_is_tty", return_value=True)
    result = runner.invoke(main, ["use", "personal", "--print"])
    assert result.exit_code == 0, result.output
    # Even with --print, stdout carries the loader (not the raw token).
    assert "ghp_xxx" not in result.output


def test_unset_emits_unsets(runner, moza_cfg):
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    result = runner.invoke(main, ["unset"])
    assert "unset MOZA_PROFILE" in result.output


def test_token_google_prints_access_token(runner, moza_cfg, mocker):
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.put.side_effect = ["ref://oauth", "ref://refresh"]
    backend.get.side_effect = lambda r: {
        "ref://oauth": b"csec",
        "ref://refresh": b"refresh-zzz",
    }[r]
    mocker.patch("moza.cli.google_installed_app_flow", return_value="refresh-zzz")
    mocker.patch("moza.cli.exchange_refresh_token", return_value="ya29-access")

    runner.invoke(
        main,
        ["login", "personal", "--service", "google",
         "--email", "me@x.com", "--client-id", "cid"],
        input="y\ncsec\n",
    )

    result = runner.invoke(main, ["token", "google"], env={"MOZA_PROFILE": "personal", "MOZA_CONFIG": str(moza_cfg)})
    assert result.exit_code == 0
    assert "ya29-access" in result.output


def test_token_google_accepts_explicit_profile_without_env(runner, moza_cfg, mocker, monkeypatch):
    """`moza token` must work without an ambient MOZA_PROFILE.

    AI agent harnesses (Claude Code, Codex) start a fresh shell per tool call, so
    env vars set by a previous `eval "$(moza use ...)"` are gone by the next call.
    Without an explicit --profile the agent has no reliable way to mint a token.
    """
    # CliRunner's env= overlays os.environ rather than replacing it, so an
    # exported MOZA_PROFILE on the developer's machine would otherwise mask
    # whether --profile did any work at all.
    monkeypatch.delenv("MOZA_PROFILE", raising=False)
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.put.side_effect = ["ref://oauth", "ref://refresh"]
    backend.get.side_effect = lambda r: {
        "ref://oauth": b"csec",
        "ref://refresh": b"refresh-zzz",
    }[r]
    mocker.patch("moza.cli.google_installed_app_flow", return_value="refresh-zzz")
    mocker.patch("moza.cli.exchange_refresh_token", return_value="ya29-access")

    runner.invoke(
        main,
        ["login", "personal", "--service", "google",
         "--email", "me@x.com", "--client-id", "cid"],
        input="y\ncsec\n",
    )

    result = runner.invoke(
        main,
        ["token", "google", "--profile", "personal"],
        env={"MOZA_CONFIG": str(moza_cfg)},
    )
    assert result.exit_code == 0
    assert "ya29-access" in result.output


def test_token_google_explicit_profile_beats_env(runner, moza_cfg, mocker):
    """--profile must win over a conflicting ambient MOZA_PROFILE.

    The env var is only a fallback (`profile or $MOZA_PROFILE`). MOZA_PROFILE is
    pinned here to a profile that does not exist, so if --profile were ignored the
    command would fail with "not found" instead of minting the token.
    """
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.put.side_effect = ["ref://oauth", "ref://refresh"]
    backend.get.side_effect = lambda r: {
        "ref://oauth": b"csec",
        "ref://refresh": b"refresh-zzz",
    }[r]
    mocker.patch("moza.cli.google_installed_app_flow", return_value="refresh-zzz")
    mocker.patch("moza.cli.exchange_refresh_token", return_value="ya29-access")

    runner.invoke(
        main,
        ["login", "personal", "--service", "google",
         "--email", "me@x.com", "--client-id", "cid"],
        input="y\ncsec\n",
    )

    result = runner.invoke(
        main,
        ["token", "google", "--profile", "personal"],
        env={"MOZA_PROFILE": "someone-else", "MOZA_CONFIG": str(moza_cfg)},
    )
    assert result.exit_code == 0, result.output
    assert "ya29-access" in result.output
    assert "someone-else" not in result.output


def test_token_without_profile_or_env_names_both_remedies(runner, moza_cfg, mocker, monkeypatch):
    """The error must name both remedies: the --profile flag and the eval pattern."""
    monkeypatch.delenv("MOZA_PROFILE", raising=False)
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    result = runner.invoke(main, ["token", "google"], env={"MOZA_CONFIG": str(moza_cfg)})
    assert result.exit_code != 0
    assert "--profile" in result.output
    assert "MOZA_PROFILE" in result.output
    assert 'eval "$(moza use' in result.output


def test_init_non_interactive_keychain(runner, moza_cfg, mocker):
    mocker.patch("moza.cli.load_backend").return_value.health_check.return_value = None
    result = runner.invoke(
        main,
        ["init", "--backend", "macos_keychain", "--service-prefix", "moza-"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(moza_cfg.read_text())
    assert payload["secrets_backend"]["type"] == "macos_keychain"


def test_init_non_interactive_gcp(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("moza.cli.subprocess.run")
    result = runner.invoke(
        main,
        ["init",
         "--backend", "gcp_secret_manager",
         "--project", "my-proj-1",
         "--bootstrap-email", "me@x.com"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(moza_cfg.read_text())
    assert payload["secrets_backend"]["project"] == "my-proj-1"
    assert payload["bootstrap"]["gcp_account"] == "me@x.com"


def test_init_yes_overwrites_existing(runner, moza_cfg, mocker):
    moza_cfg.parent.mkdir(parents=True, exist_ok=True)
    moza_cfg.write_text("{}")
    mocker.patch("moza.cli.load_backend").return_value.health_check.return_value = None
    result = runner.invoke(
        main,
        ["init", "-y", "--backend", "macos_keychain", "--service-prefix", "moza-"],
    )
    assert result.exit_code == 0, result.output


def test_login_github_token_stdin(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.put.return_value = "ref://gh"
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "github", "--username", "me", "--token-stdin"],
        input="y\nghp_pasted_token\n",
    )
    assert result.exit_code == 0, result.output
    args = backend.put.call_args[0]
    assert args[1] == b"ghp_pasted_token"


def test_login_github_ssh_key_path_skips_pat_prompt(runner, moza_cfg, mocker, tmp_path):
    mocker.patch("moza.cli.load_backend")
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    keyfile = tmp_path / "id_test"
    keyfile.write_text("PRIVATE")
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "github", "--ssh-key-path", str(keyfile)],
        input="y\n",
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(moza_cfg.read_text())
    gh = payload["profiles"]["personal"]["github"]
    assert gh["ssh_key_path"] == str(keyfile)
    assert gh["token_ref"] is None
    assert gh["ssh_key_ref"] is None


def test_login_github_ssh_key_stored_in_backend(runner, moza_cfg, mocker, tmp_path):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.put.return_value = "ref://ssh"
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    keyfile = tmp_path / "id_test"
    keyfile.write_bytes(b"PRIVATE-KEY")
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "github", "--ssh-key", str(keyfile)],
        input="y\n",
    )
    assert result.exit_code == 0, result.output
    backend.put.assert_called_once()
    args = backend.put.call_args[0]
    assert args[1] == b"PRIVATE-KEY"
    payload = json.loads(moza_cfg.read_text())
    gh = payload["profiles"]["personal"]["github"]
    assert gh["ssh_key_ref"] == "ref://ssh"
    assert gh["token_ref"] is None


def test_login_github_interactive_ssh_prompt_path(runner, moza_cfg, mocker, tmp_path):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.put.return_value = "ref://gh"
    keyfile = tmp_path / "id_test"
    keyfile.write_text("PRIVATE")
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "github"],
        input=f"y\nme\ntok\ny\n{keyfile}\npath\n",
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(moza_cfg.read_text())
    gh = payload["profiles"]["personal"]["github"]
    assert gh["token_ref"] == "ref://gh"
    assert gh["ssh_key_path"] == str(keyfile)
    assert gh["ssh_key_ref"] is None


def test_login_github_pat_and_ssh_compose_across_calls(runner, moza_cfg, mocker, tmp_path):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.put.return_value = "ref://gh"
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    runner.invoke(main, ["login", "work2", "--service", "github"], input="y\nme\ntok\nn\n")
    keyfile = tmp_path / "id_test"
    keyfile.write_text("PRIVATE")
    runner.invoke(
        main,
        ["login", "work2", "--service", "github", "--ssh-key-path", str(keyfile)],
    )
    payload = json.loads(moza_cfg.read_text())
    gh = payload["profiles"]["work2"]["github"]
    assert gh["token_ref"] == "ref://gh"
    assert gh["ssh_key_path"] == str(keyfile)


def test_preflight_keychain_passes(runner, mocker):
    mocker.patch("moza.cli.subprocess.run")
    result = runner.invoke(main, ["preflight", "--backend", "macos_keychain", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["backend"] == "macos_keychain"
    assert all(c["ok"] for c in payload["checks"])


def test_preflight_gcp_reports_missing_pieces(runner, moza_cfg, mocker):
    # gcloud --version succeeds, project describe fails, services list returns empty,
    # ADC file missing → preflight should exit non-zero with structured findings.
    import subprocess as _sp
    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["gcloud", "--version"]:
            return _sp.CompletedProcess(cmd, 0, stdout="Google Cloud SDK 999.0.0\n", stderr="")
        if cmd[:3] == ["gcloud", "projects", "describe"]:
            return _sp.CompletedProcess(cmd, 1, stdout="", stderr="permission denied")
        if cmd[:3] == ["gcloud", "services", "list"]:
            return _sp.CompletedProcess(cmd, 0, stdout="", stderr="")
        return _sp.CompletedProcess(cmd, 0, stdout="", stderr="")
    mocker.patch("moza.cli.subprocess.run", side_effect=fake_run)
    mocker.patch("moza.cli.Path.exists", return_value=False)  # ADC missing
    result = runner.invoke(
        main,
        ["preflight", "--backend", "gcp_secret_manager",
         "--project", "missing-proj", "--account", "me@x.com", "--json"],
    )
    assert result.exit_code != 0
    payload = json.loads(result.output)
    checks = {c["check"]: c for c in payload["checks"]}
    assert checks["gcloud installed"]["ok"]
    assert not checks["project 'missing-proj' accessible"]["ok"]
    assert not checks["Secret Manager API enabled"]["ok"]


def test_logout_removes_service(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.put.return_value = "ref://gh"
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    runner.invoke(main, ["login", "personal", "--service", "github"], input="y\nme\ntok\nn\n")
    result = runner.invoke(main, ["logout", "personal", "--service", "github"])
    assert result.exit_code == 0
    backend.delete.assert_called_with("ref://gh")
    payload = json.loads(moza_cfg.read_text())
    assert payload["profiles"]["personal"]["github"] is None


def test_doctor_runs_health_check(runner, moza_cfg, mocker):
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    backend = mocker.patch("moza.cli.load_backend").return_value
    result = runner.invoke(main, ["doctor"])
    assert result.exit_code == 0
    backend.health_check.assert_called_once()
    assert "OK" in result.output


def test_doctor_reports_failure(runner, moza_cfg, mocker):
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.health_check.side_effect = RuntimeError("boom")
    result = runner.invoke(main, ["doctor"])
    assert result.exit_code != 0
    assert "boom" in result.output


def test_doctor_gc_sweeps(runner, moza_cfg, mocker):
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    mocker.patch("moza.cli.load_backend").return_value
    gc = mocker.patch("moza.cli.EphemeralStore.gc")
    runner.invoke(main, ["doctor", "--gc"])
    gc.assert_called_once()


def test_init_rejects_project_name_with_space(runner, moza_cfg):
    result = runner.invoke(main, ["init"], input="1\nMy First Project\n")
    assert result.exit_code != 0
    assert "PROJECT_ID" in result.output
    assert "gcloud projects list" in result.output
    assert not moza_cfg.exists()


def test_init_rejects_uppercase_project_id(runner, moza_cfg):
    result = runner.invoke(main, ["init"], input="1\nMy-Project\n")
    assert result.exit_code != 0
    assert "PROJECT_ID" in result.output


def test_init_strips_markdown_email(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("moza.cli.subprocess.run")  # don't touch real gcloud ADC
    result = runner.invoke(
        main,
        ["init"],
        input="1\nmy-proj-1\n[a@b.com](mailto:a@b.com)\n",
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(moza_cfg.read_text())
    assert payload["bootstrap"]["gcp_account"] == "a@b.com"


def test_init_aborts_on_health_check_failure_with_actionable_message(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.health_check.side_effect = RuntimeError("permission denied: caller lacks role")
    result = runner.invoke(main, ["init"], input="1\nmy-proj-1\nme@x.com\n")
    assert result.exit_code != 0
    out = result.output
    assert "permission denied" in out.lower()
    assert "gcloud auth application-default login --account=me@x.com" in out
    assert "moza doctor" in out
    # Config should still be on disk so user can fix without re-prompting.
    assert moza_cfg.exists()


def test_init_keychain_runs_health_check(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.health_check.return_value = None
    result = runner.invoke(main, ["init"], input="3\nmoza-\n")
    assert result.exit_code == 0
    backend.health_check.assert_called_once()
    assert "OK" in result.output


def test_init_sets_quota_project_for_gcp(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.health_check.return_value = None
    sub = mocker.patch("moza.cli.subprocess.run")
    result = runner.invoke(main, ["init"], input="1\nsayu-studio\nme@x.com\n")
    assert result.exit_code == 0, result.output
    quota_calls = [
        c for c in sub.call_args_list
        if c[0][0][:4] == ["gcloud", "auth", "application-default", "set-quota-project"]
    ]
    assert len(quota_calls) == 1
    assert quota_calls[0][0][0][4] == "sayu-studio"
    assert "quota project to sayu-studio" in result.output


def test_init_warns_when_quota_project_set_fails(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("moza.cli.subprocess.run", side_effect=FileNotFoundError("gcloud"))
    result = runner.invoke(main, ["init"], input="1\nsayu-studio\nme@x.com\n")
    assert result.exit_code == 0
    assert "could not set ADC quota project" in result.output
    assert "gcloud auth application-default set-quota-project sayu-studio" in result.output


def test_login_google_shows_oauth_hint_when_client_id_missing(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.health_check.return_value = None
    backend.put.side_effect = ["ref://oauth", "ref://refresh"]
    mocker.patch("moza.cli.google_installed_app_flow", return_value="refresh-zzz")
    mocker.patch("moza.cli.subprocess.run")  # set-quota-project no-op
    runner.invoke(main, ["init"], input="1\nsayu-studio\nme@x.com\n")
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "google", "--email", "me@x.com"],
        input="y\nmy-cid\nmy-csec\n",
    )
    assert result.exit_code == 0, result.output
    assert "OAuth Desktop client" in result.output
    assert "console.cloud.google.com/apis/credentials" in result.output
    assert "sayu-studio" in result.output


def test_login_google_skips_hint_when_client_id_provided(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.health_check.return_value = None
    backend.put.side_effect = ["ref://oauth", "ref://refresh"]
    mocker.patch("moza.cli.google_installed_app_flow", return_value="refresh-zzz")
    mocker.patch("moza.cli.subprocess.run")
    runner.invoke(main, ["init"], input="1\nsayu-studio\nme@x.com\n")
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "google",
         "--email", "me@x.com", "--client-id", "cid"],
        input="y\ncsec\n",
    )
    assert result.exit_code == 0, result.output
    assert "OAuth Desktop client" not in result.output


def test_login_github_pushes_manifest(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.put.return_value = "ref://gh-token"
    mocker.patch("moza.cli.pull_manifest", return_value=None)
    push = mocker.patch("moza.cli.push_manifest")
    runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "github"],
        input="y\nmyuser\nghp_token123\nn\n",
    )
    assert result.exit_code == 0, result.output
    push.assert_called_once()


def test_login_manifest_push_failure_is_nonfatal(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.put.return_value = "ref://gh-token"
    mocker.patch("moza.cli.pull_manifest", return_value=None)
    mocker.patch("moza.cli.push_manifest", side_effect=RuntimeError("network down"))
    runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "github"],
        input="y\nmyuser\nghp_token123\nn\n",
    )
    assert result.exit_code == 0, result.output
    assert "could not sync config manifest" in result.output
    assert "network down" in result.output


def test_login_keychain_does_not_push_manifest(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.put.return_value = "ref://gh-token"
    push = mocker.patch("moza.cli.push_manifest")
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "github"],
        input="y\nmyuser\nghp_token123\nn\n",
    )
    assert result.exit_code == 0, result.output
    push.assert_not_called()


def test_logout_pushes_manifest(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.put.return_value = "ref://gh"
    mocker.patch("moza.cli.pull_manifest", return_value=None)
    push = mocker.patch("moza.cli.push_manifest")
    runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    runner.invoke(main, ["login", "personal", "--service", "github"],
                  input="y\nme\ntok\nn\n")
    push.reset_mock()
    result = runner.invoke(main, ["logout", "personal", "--service", "github"])
    assert result.exit_code == 0, result.output
    push.assert_called_once()


def test_login_rejects_reserved_manifest_profile_name(runner, moza_cfg, mocker):
    mocker.patch("moza.cli.load_backend")
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    result = runner.invoke(
        main,
        ["login", "moza-config-manifest", "--service", "github", "--username", "u"],
        input="y\n",
    )
    assert result.exit_code != 0
    assert "reserved" in result.output.lower()


def _manifest_cfg():
    from moza.config import (BackendConfig, Config, GitHubService, Profile,
                            SecretNaming)
    return Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="gcp_secret_manager", options={"project": "p1"}),
        bootstrap={"gcp_account": "me@x.com"},
        secret_naming=SecretNaming(default="moza-{profile}-{service}-{kind}",
                                   slack_token="moza-{profile}-slack-{workspace}-token"),
        profiles={"work": Profile(name="work",
                                  github=GitHubService(username="u", host="github.com",
                                                       token_ref="ref://x"))},
    )


def test_init_offers_and_imports_manifest(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("moza.cli.subprocess.run")
    mocker.patch("moza.cli.pull_manifest", return_value=_manifest_cfg())
    result = runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
        input="y\n",
    )
    assert result.exit_code == 0, result.output
    assert "Imported 1 profiles" in result.output
    payload = json.loads(moza_cfg.read_text())
    assert "work" in payload["profiles"]


def test_init_no_import_flag_skips_manifest(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("moza.cli.subprocess.run")
    mocker.patch("moza.cli.pull_manifest", return_value=_manifest_cfg())
    result = runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager", "--no-import",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(moza_cfg.read_text())
    assert payload["profiles"] == {}


def test_init_keychain_never_pulls_manifest(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.health_check.return_value = None
    pull = mocker.patch("moza.cli.pull_manifest")
    result = runner.invoke(main, ["init"], input="3\nmoza-\n")
    assert result.exit_code == 0, result.output
    pull.assert_not_called()


def test_init_user_declines_manifest_import(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("moza.cli.subprocess.run")
    mocker.patch("moza.cli.pull_manifest", return_value=_manifest_cfg())
    result = runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
        input="n\n",
    )
    assert result.exit_code == 0, result.output
    assert "Next:" in result.output
    payload = json.loads(moza_cfg.read_text())
    assert payload["profiles"] == {}


def test_sync_dry_run_reports_diff_and_writes_nothing(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("moza.cli.subprocess.run")
    mocker.patch("moza.cli.pull_manifest", return_value=None)
    runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager", "--no-import",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    before = moza_cfg.read_text()
    mocker.patch("moza.cli.pull_manifest", return_value=_manifest_cfg())
    result = runner.invoke(main, ["sync", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "+ add:" in result.output and "work" in result.output
    assert moza_cfg.read_text() == before  # unchanged


def test_sync_applies_with_yes(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("moza.cli.subprocess.run")
    mocker.patch("moza.cli.pull_manifest", return_value=None)
    runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager", "--no-import",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    mocker.patch("moza.cli.pull_manifest", return_value=_manifest_cfg())
    result = runner.invoke(main, ["sync", "-y"])
    assert result.exit_code == 0, result.output
    payload = json.loads(moza_cfg.read_text())
    assert "work" in payload["profiles"]


def test_sync_no_manifest_errors(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("moza.cli.subprocess.run")
    mocker.patch("moza.cli.pull_manifest", return_value=None)
    runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager", "--no-import",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    result = runner.invoke(main, ["sync"])
    assert result.exit_code != 0
    assert "no manifest" in result.output.lower()


def test_sync_requires_cloud_backend(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.health_check.return_value = None
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    result = runner.invoke(main, ["sync"])
    assert result.exit_code != 0
    assert "cloud backend" in result.output.lower()


def test_sync_already_in_sync(runner, moza_cfg, mocker):
    import moza.config as mozacfg
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("moza.cli.subprocess.run")
    mocker.patch("moza.cli.pull_manifest", return_value=None)
    runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager", "--no-import",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    # make local config identical to the manifest we'll pull
    moza_cfg.write_text(mozacfg.serialize_config(_manifest_cfg()))
    mocker.patch("moza.cli.pull_manifest", return_value=_manifest_cfg())
    result = runner.invoke(main, ["sync"])
    assert result.exit_code == 0, result.output
    assert "already in sync" in result.output


def test_sync_user_declines_confirm_aborts(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("moza.cli.subprocess.run")
    mocker.patch("moza.cli.pull_manifest", return_value=None)
    runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager", "--no-import",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    before = moza_cfg.read_text()
    mocker.patch("moza.cli.pull_manifest", return_value=_manifest_cfg())
    result = runner.invoke(main, ["sync"], input="n\n")
    assert result.exit_code != 0
    assert moza_cfg.read_text() == before  # nothing written


def test_push_command_pushes_manifest(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    mocker.patch("moza.cli.subprocess.run")
    mocker.patch("moza.cli.pull_manifest", return_value=None)
    runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager", "--no-import",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    push = mocker.patch("moza.cli.push_manifest")
    result = runner.invoke(main, ["push"])
    assert result.exit_code == 0, result.output
    push.assert_called_once()
    assert "pushed config manifest" in result.output


def test_push_command_noop_on_keychain(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.health_check.return_value = None
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    push = mocker.patch("moza.cli.push_manifest")
    result = runner.invoke(main, ["push"])
    assert result.exit_code == 0, result.output
    push.assert_not_called()
    assert "no-op" in result.output.lower()


def test_init_yes_auto_imports_manifest_without_prompt(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("moza.cli.subprocess.run")
    mocker.patch("moza.cli.pull_manifest", return_value=_manifest_cfg())
    result = runner.invoke(
        main,
        ["init", "-y", "--backend", "gcp_secret_manager",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    assert result.exit_code == 0, result.output
    assert "Imported 1 profiles" in result.output
    payload = json.loads(moza_cfg.read_text())
    assert "work" in payload["profiles"]


def test_login_atlassian_stores_token_and_updates_config(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.put.return_value = "ref://atl-token"
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    result = runner.invoke(
        main,
        [
            "login", "personal", "--service", "atlassian",
            "--atlassian-email", "me@company.com",
            "--base-url", "https://company.atlassian.net",
            "--token-stdin",
        ],
        input="y\nmy-api-token\n",
    )
    assert result.exit_code == 0, result.output
    assert "stored atlassian identity" in result.output
    payload = json.loads(moza_cfg.read_text())
    atl = payload["profiles"]["personal"]["atlassian"]
    assert atl["email"] == "me@company.com"
    assert atl["base_url"] == "https://company.atlassian.net"
    assert atl["api_token_ref"] == "ref://atl-token"


def test_list_shows_atlassian(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.put.return_value = "ref://atl-token"
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    runner.invoke(
        main,
        [
            "login", "personal", "--service", "atlassian",
            "--atlassian-email", "me@company.com",
            "--base-url", "https://company.atlassian.net",
            "--token-stdin",
        ],
        input="y\nmy-api-token\n",
    )
    result = runner.invoke(main, ["list"])
    assert result.exit_code == 0, result.output
    assert "atlassian:me@company.com" in result.output


def test_logout_atlassian_removes_service(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.put.return_value = "ref://atl-token"
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    runner.invoke(
        main,
        [
            "login", "personal", "--service", "atlassian",
            "--atlassian-email", "me@company.com",
            "--base-url", "https://company.atlassian.net",
            "--token-stdin",
        ],
        input="y\nmy-api-token\n",
    )
    result = runner.invoke(main, ["logout", "personal", "--service", "atlassian"])
    assert result.exit_code == 0, result.output
    backend.delete.assert_called_with("ref://atl-token")
    payload = json.loads(moza_cfg.read_text())
    assert payload["profiles"]["personal"]["atlassian"] is None


def test_token_atlassian_prints_api_token(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.put.return_value = "ref://atl-token"
    backend.get.return_value = b"my-secret-api-token"
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    runner.invoke(
        main,
        [
            "login", "personal", "--service", "atlassian",
            "--atlassian-email", "me@company.com",
            "--base-url", "https://company.atlassian.net",
            "--token-stdin",
        ],
        input="y\nmy-secret-api-token\n",
    )
    result = runner.invoke(
        main, ["token", "atlassian"],
        env={"MOZA_PROFILE": "personal", "MOZA_CONFIG": str(moza_cfg)},
    )
    assert result.exit_code == 0, result.output
    assert "my-secret-api-token" in result.output


def test_login_notion_stores_token_and_updates_config(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.put.return_value = "ref://notion-token"
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "notion", "--token-stdin"],
        input="y\nmy-notion-token\n",
    )
    assert result.exit_code == 0, result.output
    assert "stored notion identity" in result.output
    payload = json.loads(moza_cfg.read_text())
    assert payload["profiles"]["personal"]["notion"]["api_token_ref"] == "ref://notion-token"


def test_list_shows_notion(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.put.return_value = "ref://notion-token"
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    runner.invoke(
        main,
        ["login", "personal", "--service", "notion", "--token-stdin"],
        input="y\nmy-notion-token\n",
    )
    result = runner.invoke(main, ["list"])
    assert result.exit_code == 0, result.output
    assert "notion" in result.output


def test_logout_notion_removes_service(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.put.return_value = "ref://notion-token"
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    runner.invoke(
        main,
        ["login", "personal", "--service", "notion", "--token-stdin"],
        input="y\nmy-notion-token\n",
    )
    result = runner.invoke(main, ["logout", "personal", "--service", "notion"])
    assert result.exit_code == 0, result.output
    backend.delete.assert_called_with("ref://notion-token")
    payload = json.loads(moza_cfg.read_text())
    assert payload["profiles"]["personal"]["notion"] is None


def test_token_notion_prints_api_token(runner, moza_cfg, mocker):
    backend = mocker.patch("moza.cli.load_backend").return_value
    backend.put.return_value = "ref://notion-token"
    backend.get.return_value = b"my-secret-notion-token"
    runner.invoke(main, ["init"], input="3\nmoza-\n")
    runner.invoke(
        main,
        ["login", "personal", "--service", "notion", "--token-stdin"],
        input="y\nmy-secret-notion-token\n",
    )
    result = runner.invoke(
        main, ["token", "notion"],
        env={"MOZA_PROFILE": "personal", "MOZA_CONFIG": str(moza_cfg)},
    )
    assert result.exit_code == 0, result.output
    assert "my-secret-notion-token" in result.output


def test_env_sync_writes_ambient_and_wires_zshenv(monkeypatch, tmp_path):
    from click.testing import CliRunner
    from moza.cli import main
    from moza.config import (Config, BackendConfig, SecretNaming, Profile,
                             ProjectEnvScope, save_config)
    monkeypatch.setenv("MOZA_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("HOME", str(tmp_path))
    save_config(Config(schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={}, secret_naming=SecretNaming(default="d", slack_token="s"),
        profiles={"work": Profile(name="work", project_env=[
            ProjectEnvScope(match="*/work", env={"AWS_PROFILE": "work"})])}))
    res = CliRunner().invoke(main, ["env", "sync"])
    assert res.exit_code == 0, res.output
    ambient = (tmp_path / "config.json").parent / "ambient.zsh"
    assert 'export AWS_PROFILE="work"' in ambient.read_text()
    assert str(ambient) in (tmp_path / ".zshenv").read_text()
    assert "work" in res.output
