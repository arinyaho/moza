import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from mien.cli import main


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mien_cfg(monkeypatch, tmp_path):
    p = tmp_path / "mien.json"
    monkeypatch.setenv("MIEN_CONFIG", str(p))
    return p


def test_list_no_config(runner, mien_cfg):
    result = runner.invoke(main, ["list"])
    assert result.exit_code != 0
    assert "mien init" in result.output


def test_status_when_unset(runner, mien_cfg, monkeypatch):
    monkeypatch.delenv("MIEN_PROFILE", raising=False)
    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0
    assert "no profile active" in result.output.lower()


def test_status_active(runner, mien_cfg, monkeypatch):
    monkeypatch.setenv("MIEN_PROFILE", "personal")
    result = runner.invoke(main, ["status"])
    assert "personal" in result.output


def test_init_writes_keychain_skeleton(runner, mien_cfg):
    result = runner.invoke(main, ["init"], input="3\nmien-\n")
    assert result.exit_code == 0, result.output
    payload = json.loads(mien_cfg.read_text())
    assert payload["secrets_backend"]["type"] == "macos_keychain"
    assert payload["profiles"] == {}


def test_list_after_init(runner, mien_cfg):
    runner.invoke(main, ["init"], input="3\nmien-\n")
    result = runner.invoke(main, ["list"])
    assert result.exit_code == 0
    assert "no profiles" in result.output.lower()


def test_whoami_unknown_profile(runner, mien_cfg):
    runner.invoke(main, ["init"], input="3\nmien-\n")
    result = runner.invoke(main, ["whoami", "nope"])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def _rich_profile_cfg(tmp_path, monkeypatch):
    from mien.config import (AtlassianService, AWSService, BackendConfig, Config,
                             GitHubService, GoogleService, NotionService, Profile,
                             SecretNaming, SlackWorkspace, save_config)
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "c.json"))
    save_config(Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={}, secret_naming=SecretNaming(default="d", slack_token="s"),
        profiles={"work": Profile(
            name="work",
            google=GoogleService(email="me@acme.example", oauth_client_id="c",
                                 oauth_client_secret_ref=None, refresh_token_ref=None,
                                 adc_ref=None, gcloud_config_name="work",
                                 default_project=None, gcloud_login_required=True),
            github=GitHubService(username="octocat", host="github.com", token_ref="r"),
            slack=[SlackWorkspace(workspace="team-a", team_id=None, user_token_ref="r")],
            aws=AWSService(profile="acme", region="us-west-1",
                           access_key_id_ref=None, secret_access_key_ref=None),
            atlassian=AtlassianService(email="me@acme.example", api_token_ref="r",
                                       base_url="https://acme.atlassian.net"),
            notion=NotionService(api_token_ref="r"),
            owns_remotes=["github.com/acme-*/*"],
            default_for=["*/Projects/acme*"],
        )},
    ))


def test_whoami_card_shows_the_whole_bundled_identity(runner, tmp_path, monkeypatch):
    _rich_profile_cfg(tmp_path, monkeypatch)
    result = runner.invoke(main, ["whoami", "work"])
    assert result.exit_code == 0
    out = result.output
    assert "one identity, every provider" in out
    for token in ["me@acme.example", "octocat", "team-a", "acme (us-west-1)",
                  "acme.atlassian.net", "notion", "github.com/acme-*/*",
                  "*/Projects/acme*"]:
        assert token in out, token


def test_whoami_card_omits_absent_providers(runner, tmp_path, monkeypatch):
    from mien.config import (BackendConfig, Config, GitHubService, Profile,
                             SecretNaming, save_config)
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "c.json"))
    save_config(Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={}, secret_naming=SecretNaming(default="d", slack_token="s"),
        profiles={"solo": Profile(
            name="solo",
            github=GitHubService(username="octocat", host="github.com", token_ref="r"))},
    ))
    result = runner.invoke(main, ["whoami", "solo"])
    assert result.exit_code == 0
    assert "github" in result.output and "octocat" in result.output
    # No google/aws/slack lines for a profile that doesn't have them.
    assert "google" not in result.output and "aws" not in result.output


def test_whoami_json_flag_still_emits_machine_readable(runner, tmp_path, monkeypatch):
    _rich_profile_cfg(tmp_path, monkeypatch)
    result = runner.invoke(main, ["whoami", "work", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["name"] == "work" and data["github"] == "octocat"
    assert data["owns_remotes"] == ["github.com/acme-*/*"]


def _project_env(tmp_path, monkeypatch, *profiles):
    from mien.config import (BackendConfig, Config, Profile, SecretNaming,
                             save_config)
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("MIEN_PROFILE", raising=False)
    save_config(Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={}, secret_naming=SecretNaming(default="d", slack_token="s"),
        profiles={p: Profile(name=p) for p in profiles},
    ))
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr("mien.cli._logical_cwd", lambda: str(ws))
    return ws


def test_which_refuses_an_unapproved_mien(tmp_path, monkeypatch):
    """Security: a checked-out .mien must NOT drive the acting identity until the
    user approves it — `which`/`run` fail loud rather than silently route."""
    ws = _project_env(tmp_path, monkeypatch, "work")
    (ws / ".mien").write_text("work\n")
    result = CliRunner().invoke(main, ["which"])
    assert result.exit_code != 0
    assert "not allowed" in result.output and "mien allow" in result.output


def test_allow_then_which_routes_to_the_declared_profile(tmp_path, monkeypatch):
    ws = _project_env(tmp_path, monkeypatch, "work")
    (ws / ".mien").write_text("work\n")
    assert CliRunner().invoke(main, ["allow"]).exit_code == 0
    result = CliRunner().invoke(main, ["which"])
    assert result.exit_code == 0 and result.output.strip() == "work"


def test_claim_writes_allows_and_routes_in_one_step(tmp_path, monkeypatch):
    ws = _project_env(tmp_path, monkeypatch, "arinyaho")
    assert CliRunner().invoke(main, ["claim", "arinyaho"]).exit_code == 0
    assert (ws / ".mien").read_text().strip() == "arinyaho"
    assert CliRunner().invoke(main, ["which"]).output.strip() == "arinyaho"
    # .mien added to the global git ignore, not the repo.
    assert ".mien" in (tmp_path / "xdg" / "git" / "ignore").read_text()


def test_claim_with_no_arg_picks_a_profile_interactively(tmp_path, monkeypatch):
    ws = _project_env(tmp_path, monkeypatch, "arinyaho", "work")  # sorted: arinyaho, work
    result = CliRunner().invoke(main, ["claim"], input="2\n")  # pick 'work'
    assert result.exit_code == 0, result.output
    assert (ws / ".mien").read_text().strip() == "work"
    assert CliRunner().invoke(main, ["which"]).output.strip() == "work"


def test_claim_with_no_arg_approves_an_existing_declaration(tmp_path, monkeypatch):
    ws = _project_env(tmp_path, monkeypatch, "work")
    (ws / ".mien").write_text("work\n")
    result = CliRunner().invoke(main, ["claim"])  # no prompt — .mien already names it
    assert result.exit_code == 0 and "approving" in result.output
    assert CliRunner().invoke(main, ["which"]).output.strip() == "work"


def test_claim_rejects_an_unknown_profile(tmp_path, monkeypatch):
    _project_env(tmp_path, monkeypatch, "arinyaho")
    result = CliRunner().invoke(main, ["claim", "ghost"])
    assert result.exit_code != 0 and "not found" in result.output


def test_active_profile_overrides_an_unapproved_declaration(tmp_path, monkeypatch):
    ws = _project_env(tmp_path, monkeypatch, "work", "arinyaho")
    (ws / ".mien").write_text("work\n")
    monkeypatch.setenv("MIEN_PROFILE", "arinyaho")
    result = CliRunner().invoke(main, ["which"])
    assert result.exit_code == 0 and "arinyaho" in result.output


def test_changing_the_declaration_reblocks_until_reapproved(tmp_path, monkeypatch):
    ws = _project_env(tmp_path, monkeypatch, "work", "arinyaho")
    (ws / ".mien").write_text("work\n")
    CliRunner().invoke(main, ["allow"])
    (ws / ".mien").write_text("arinyaho\n")  # edited to a different profile
    result = CliRunner().invoke(main, ["which"])
    assert result.exit_code != 0 and "not allowed" in result.output


def test_git_sync_writes_includeif_from_owns_remotes(tmp_path, monkeypatch):
    from mien.config import (BackendConfig, Config, GoogleService, Profile,
                             SecretNaming, save_config)
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr("mien.cli._ensure_git_include", lambda _p: True)
    save_config(Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={}, secret_naming=SecretNaming(default="d", slack_token="s"),
        profiles={"work": Profile(
            name="work", owns_remotes=["github.com/acme-inc/*"],
            git_email="me@acme.example", git_name="acme-me")},
    ))
    result = CliRunner().invoke(main, ["git", "sync"])
    assert result.exit_code == 0, result.output
    main_gc = (tmp_path / "gitconfig").read_text()
    assert "hasconfig:remote.*.url:**/*github.com/acme-inc/**" in main_gc
    assert "hasconfig:remote.*.url:**github.com:acme-inc/**" in main_gc
    prof_gc = (tmp_path / "git" / "work.gitconfig").read_text()
    assert "email = me@acme.example" in prof_gc and "name = acme-me" in prof_gc


def test_git_sync_asks_for_a_missing_git_email_and_saves_it(tmp_path, monkeypatch):
    from mien.config import (BackendConfig, Config, GoogleService, Profile,
                             SecretNaming, load_config, save_config)
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr("mien.cli._ensure_git_include", lambda _p: True)
    save_config(Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={}, secret_naming=SecretNaming(default="d", slack_token="s"),
        profiles={"work": Profile(
            name="work", owns_remotes=["github.com/acme-inc/*"],
            google=GoogleService(
                email="me@acme.example", oauth_client_id="c",
                oauth_client_secret_ref=None, refresh_token_ref=None, adc_ref=None,
                gcloud_config_name="work", default_project=None,
                gcloud_login_required=True))},
    ))
    # Accept the offered defaults (google email, github-less → email local part).
    result = CliRunner().invoke(main, ["git", "sync"], input="\n\n")
    assert result.exit_code == 0, result.output
    saved = load_config().profiles["work"]
    assert saved.git_email == "me@acme.example"  # persisted after the prompt
    assert "email = me@acme.example" in (tmp_path / "git" / "work.gitconfig").read_text()


def test_git_sync_errors_when_nothing_to_sync(tmp_path, monkeypatch):
    from mien.config import (BackendConfig, Config, Profile, SecretNaming,
                             save_config)
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "config.json"))
    save_config(Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={}, secret_naming=SecretNaming(default="d", slack_token="s"),
        profiles={"work": Profile(name="work")},  # no owns_remotes, no .mien
    ))
    result = CliRunner().invoke(main, ["git", "sync"])
    assert result.exit_code != 0 and "nothing to sync" in result.output


def _github_profile(runner, mien_cfg, mocker, username="octocat"):
    mocker.patch("mien.cli.load_backend").return_value.put.return_value = "ref://gh"
    runner.invoke(main, ["init"], input="3\nmien-\n")
    runner.invoke(main, ["login", "personal", "--service", "github"],
                  input=f"y\n{username}\nghp_x\nn\n")


def test_whoami_offline_still_prints_config_without_probing(runner, mien_cfg, mocker):
    """The default path must not touch the network — it is the fast, offline view."""
    _github_profile(runner, mien_cfg, mocker)
    probe = mocker.patch("mien.cli.probe_github")
    result = runner.invoke(main, ["whoami", "personal"])
    assert result.exit_code == 0
    assert "octocat" in result.output
    probe.assert_not_called()


def test_whoami_live_reports_match(runner, mien_cfg, mocker):
    from mien.verify import ProbeResult, Status
    _github_profile(runner, mien_cfg, mocker)
    mocker.patch("mien.cli.build_env").return_value.env = {"GH_TOKEN": "t"}
    mocker.patch("mien.cli.probe_github",
                 return_value=ProbeResult("github", "octocat", "octocat", Status.MATCH))
    result = runner.invoke(main, ["whoami", "personal", "--live"])
    assert result.exit_code == 0, result.output
    assert "octocat" in result.output
    assert "match" in result.output.lower()


def test_whoami_live_mismatch_exits_nonzero(runner, mien_cfg, mocker):
    """The whole point: a wrong live identity must fail, so it can gate a
    destructive action chained after it."""
    from mien.verify import ProbeResult, Status
    _github_profile(runner, mien_cfg, mocker)
    mocker.patch("mien.cli.build_env").return_value.env = {"GH_TOKEN": "t"}
    mocker.patch("mien.cli.probe_github",
                 return_value=ProbeResult("github", "octocat", "someone-else",
                                          Status.MISMATCH))
    result = runner.invoke(main, ["whoami", "personal", "--live"])
    assert result.exit_code != 0
    assert "someone-else" in result.output
    assert "mismatch" in result.output.lower()


def test_whoami_live_unauthorized_exits_nonzero(runner, mien_cfg, mocker):
    """A revoked token is a problem to surface, distinct from a mismatch."""
    from mien.verify import ProbeResult, Status
    _github_profile(runner, mien_cfg, mocker)
    mocker.patch("mien.cli.build_env").return_value.env = {"GH_TOKEN": "t"}
    mocker.patch("mien.cli.probe_github",
                 return_value=ProbeResult("github", "octocat", None,
                                          Status.UNAUTHORIZED, "HTTP 401"))
    result = runner.invoke(main, ["whoami", "personal", "--live"])
    assert result.exit_code != 0
    assert "unauthorized" in result.output.lower()


def test_whoami_live_cleans_ephemeral_credential_files(runner, tmp_path, monkeypatch, mocker):
    """--live builds the profile env, which writes plaintext credential files to
    $TMPDIR/mien. A verification command must not leave credentials on disk."""
    from mien.config import (BackendConfig, Config, Profile, SecretNaming,
                             SlackWorkspace, GitHubService, save_config)
    from mien.verify import ProbeResult, Status
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    save_config(Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={}, secret_naming=SecretNaming(default="d", slack_token="s"),
        profiles={"personal": Profile(
            name="personal",
            github=GitHubService(username="octocat", host="github.com", token_ref="ref://gh"),
            slack=[SlackWorkspace(workspace="team-a", team_id=None, user_token_ref="ref://slack")],
        )},
    ))
    mocker.patch("mien.cli.load_backend").return_value.get.return_value = b"xoxp-secret"
    mocker.patch("mien.cli.probe_github",
                 return_value=ProbeResult("github", "octocat", "octocat", Status.MATCH))

    result = runner.invoke(main, ["whoami", "personal", "--live"])
    assert result.exit_code == 0, result.output
    # The slack workspace makes build_env write an ephemeral file; it must be gone.
    assert list((tmp_path / "mien").iterdir()) == []


def test_whoami_live_names_google_when_it_cannot_be_probed(runner, mien_cfg, mocker):
    """A gcloud-login-only google (no client-secret/refresh-token ref) cannot be
    verified by the refresh-token probe. It must be named as unchecked, not
    silently dropped — otherwise a clean report gives false confidence that
    google was verified when it never was."""
    from mien.config import (BackendConfig, Config, Profile, SecretNaming,
                             GoogleService, GitHubService, save_config)
    from mien.verify import ProbeResult, Status
    save_config(Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={}, secret_naming=SecretNaming(default="d", slack_token="s"),
        profiles={"personal": Profile(
            name="personal",
            github=GitHubService(username="octocat", host="github.com", token_ref="ref://gh"),
            google=GoogleService(
                email="me@example.com", oauth_client_id="cid",
                oauth_client_secret_ref=None, refresh_token_ref="",
                adc_ref=None, gcloud_config_name="personal",
                default_project=None, gcloud_login_required=True,
            ),
        )},
    ))
    mocker.patch("mien.cli.build_env").return_value.env = {}
    mocker.patch("mien.cli.probe_github",
                 return_value=ProbeResult("github", "octocat", "octocat", Status.MATCH))
    result = runner.invoke(main, ["whoami", "personal", "--live"])
    assert result.exit_code == 0, result.output
    assert "not checked" in result.output.lower()
    assert "google" in result.output.lower()


def test_whoami_live_names_unchecked_services(runner, mien_cfg, mocker):
    """A profile with slack/notion must not read as fully verified when only
    github was probed."""
    from mien.config import (BackendConfig, Config, Profile, SecretNaming,
                             SlackWorkspace, GitHubService, NotionService, save_config)
    from mien.verify import ProbeResult, Status
    save_config(Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={}, secret_naming=SecretNaming(default="d", slack_token="s"),
        profiles={"personal": Profile(
            name="personal",
            github=GitHubService(username="octocat", host="github.com", token_ref="ref://gh"),
            slack=[SlackWorkspace(workspace="team-a", team_id=None, user_token_ref="ref://s")],
            notion=NotionService(api_token_ref="ref://n"),
        )},
    ))
    mocker.patch("mien.cli.build_env").return_value.env = {}
    mocker.patch("mien.cli.probe_github",
                 return_value=ProbeResult("github", "octocat", "octocat", Status.MATCH))
    result = runner.invoke(main, ["whoami", "personal", "--live"])
    assert result.exit_code == 0, result.output
    assert "not checked" in result.output.lower()
    assert "slack" in result.output and "notion" in result.output


def test_whoami_live_unreachable_does_not_fail(runner, mien_cfg, mocker):
    """Could-not-check is not the same as wrong. A network blip must not report a
    problem that isn't there — it is surfaced, but does not fail the command."""
    from mien.verify import ProbeResult, Status
    _github_profile(runner, mien_cfg, mocker)
    mocker.patch("mien.cli.build_env").return_value.env = {"GH_TOKEN": "t"}
    mocker.patch("mien.cli.probe_github",
                 return_value=ProbeResult("github", "octocat", None,
                                          Status.UNREACHABLE, "timed out"))
    result = runner.invoke(main, ["whoami", "personal", "--live"])
    assert result.exit_code == 0
    assert "unreachable" in result.output.lower()


def test_login_github_stores_token_and_updates_config(runner, mien_cfg, mocker):
    mocker.patch("mien.cli.load_backend").return_value.put.return_value = "ref://gh-token"
    runner.invoke(main, ["init"], input="3\nmien-\n")
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "github"],
        input="y\nmyuser\nghp_token123\nn\n",
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(mien_cfg.read_text())
    gh = payload["profiles"]["personal"]["github"]
    assert gh["username"] == "myuser"
    assert gh["host"] == "github.com"
    assert gh["token_ref"] == "ref://gh-token"


def test_login_slack_requires_workspace(runner, mien_cfg):
    runner.invoke(main, ["init"], input="3\nmien-\n")
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "slack"],
        input="y\n",
    )
    assert result.exit_code != 0
    assert "--workspace" in result.output


def test_login_slack_appends_workspace(runner, mien_cfg, mocker):
    mocker.patch("mien.cli.load_backend").return_value.put.side_effect = [
        "ref://slack-a",
        "ref://slack-b",
    ]
    runner.invoke(main, ["init"], input="3\nmien-\n")
    runner.invoke(main, ["login", "personal", "--service", "slack", "--workspace", "team-a"], input="y\nxoxp-aaa\n")
    runner.invoke(main, ["login", "personal", "--service", "slack", "--workspace", "team-b"], input="xoxp-bbb\n")
    payload = json.loads(mien_cfg.read_text())
    workspaces = payload["profiles"]["personal"]["slack"]
    assert [w["workspace"] for w in workspaces] == ["team-a", "team-b"]
    assert workspaces[0]["user_token_ref"] == "ref://slack-a"


def test_login_google_runs_oauth_and_stores(runner, mien_cfg, mocker):
    mocker.patch("mien.cli.google_installed_app_flow", return_value="refresh-zzz")
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.put.side_effect = [
        "ref://oauth-secret",
        "ref://refresh",
    ]
    runner.invoke(main, ["init"], input="3\nmien-\n")
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
    payload = json.loads(mien_cfg.read_text())
    g = payload["profiles"]["personal"]["google"]
    assert g["email"] == "me@example.com"
    assert g["oauth_client_id"] == "cid"
    assert g["refresh_token_ref"] == "ref://refresh"
    assert g["oauth_client_secret_ref"] == "ref://oauth-secret"
    assert g["gcloud_config_name"] == "personal"


def test_use_routes_secrets_through_ephemeral_file(runner, mien_cfg, mocker, tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    runner.invoke(main, ["init"], input="3\nmien-\n")
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.put.return_value = "ref://gh"
    runner.invoke(main, ["login", "personal", "--service", "github"], input="y\nme\nghp_xxx\nn\n")

    backend.get.return_value = b"ghp_xxx"
    result = runner.invoke(main, ["use", "personal"])
    assert result.exit_code == 0, result.output

    # Token must never appear on stdout: that was the original leak vector
    # (caller forgets `eval`, stdout lands in transcript / shell history / ps).
    assert "ghp_xxx" not in result.output

    # Output is a one-liner that sources a path under TMPDIR/mien and rm's it.
    import re
    m = re.match(r"\. '([^']+)' && rm -f '\1'", result.output.strip())
    assert m, result.output
    script = Path(m.group(1))
    body = script.read_text()
    assert "export MIEN_PROFILE='personal'" in body
    assert "export GH_TOKEN='ghp_xxx'" in body


def _use_setup(runner, mocker, tmp_path, monkeypatch, *, slack=True):
    """A profile that makes build_env write an ephemeral file, with a scoped
    TMPDIR so the files land under tmp_path/mien."""
    from mien.config import (BackendConfig, Config, Profile, SecretNaming,
                             SlackWorkspace, GitHubService, save_config)
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    ws = [SlackWorkspace(workspace="team-a", team_id=None, user_token_ref="ref://s")] if slack else []
    save_config(Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={}, secret_naming=SecretNaming(default="d", slack_token="s"),
        profiles={"personal": Profile(
            name="personal",
            github=GitHubService(username="me", host="github.com", token_ref="ref://gh"),
            slack=ws,
        )},
    ))
    mocker.patch("mien.cli.load_backend").return_value.get.return_value = b"xoxp-secret"


def test_use_attributes_files_to_the_owner_pid(runner, tmp_path, monkeypatch, mocker):
    """--owner-pid keys the ephemeral files to the calling shell, not the
    short-lived mien process. The wrapper passes $$ so the files live as long as
    the shell that sourced them — otherwise gc, seeing mien's already-dead pid,
    deletes credentials the shell is still using."""
    _use_setup(runner, mocker, tmp_path, monkeypatch)
    result = runner.invoke(main, ["use", "personal", "--print", "--owner-pid", "999999"])
    assert result.exit_code == 0, result.output
    files = list((tmp_path / "mien").iterdir())
    # Every ephemeral file (slack token map, env loader) is keyed to 999999.
    keyed = [f for f in files if f.name.startswith("999999-")]
    assert keyed, f"no files attributed to the owner pid: {[f.name for f in files]}"


def test_use_leaves_the_files_on_disk_for_the_shell_to_source(runner, tmp_path, monkeypatch, mocker):
    """The activation contract: unlike exec/run, `use` must NOT clean up — the
    calling shell sources these after the process exits. A well-meaning cleanup
    added to use_cmd would break activation silently; this pins against it."""
    _use_setup(runner, mocker, tmp_path, monkeypatch)
    result = runner.invoke(main, ["use", "personal", "--print", "--owner-pid", "999999"])
    assert result.exit_code == 0, result.output
    # The credential files (keyed to the owner pid) must survive — a cleanup
    # added to use_cmd would delete exactly these, which is what breaks
    # activation. Checking the pid-keyed files, not just "any file", is what
    # makes this bite: the env loader has a different name and would survive a
    # pid-scoped cleanup, hiding the break.
    remaining = [f.name for f in (tmp_path / "mien").iterdir()]
    assert any(n.startswith("999999-") for n in remaining), \
        f"use must leave its owner-pid credential files on disk; found {remaining}"


def test_use_refuses_when_stdout_is_a_tty(runner, mien_cfg, mocker, monkeypatch):
    runner.invoke(main, ["init"], input="3\nmien-\n")
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.put.return_value = "ref://gh"
    runner.invoke(main, ["login", "personal", "--service", "github"], input="y\nme\nghp_xxx\nn\n")

    # Force the TTY heuristic on Click's StringIO so we can test the guard.
    mocker.patch("mien.cli._stdout_is_tty", return_value=True)
    result = runner.invoke(main, ["use", "personal"])

    # Must exit non-zero with a hint at the wrapper / eval form. Crucially,
    # the secret must NOT have been resolved or printed.
    assert result.exit_code != 0
    assert "ghp_xxx" not in result.output
    assert "eval" in result.output or "mien-use" in result.output


def test_use_print_flag_overrides_tty_guard(runner, mien_cfg, mocker, tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    runner.invoke(main, ["init"], input="3\nmien-\n")
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.put.return_value = "ref://gh"
    runner.invoke(main, ["login", "personal", "--service", "github"], input="y\nme\nghp_xxx\nn\n")

    backend.get.return_value = b"ghp_xxx"
    mocker.patch("mien.cli._stdout_is_tty", return_value=True)
    result = runner.invoke(main, ["use", "personal", "--print"])
    assert result.exit_code == 0, result.output
    # Even with --print, stdout carries the loader (not the raw token).
    assert "ghp_xxx" not in result.output


def test_exec_removes_ephemeral_files_after_child_exits(
    runner, mien_cfg, mocker, tmp_path, monkeypatch
):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    runner.invoke(main, ["init"], input="3\nmien-\n")
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.put.return_value = "ref://slack"
    # A slack workspace guarantees build_env writes an ephemeral token file,
    # so the assertions below can't pass vacuously.
    runner.invoke(
        main,
        ["login", "demo", "--service", "slack", "--workspace", "acme"],
        input="y\nxoxp-secret\n",
    )

    backend.get.return_value = b"xoxp-secret"
    seen: dict = {}

    def fake_call(argv, env=None):
        path = Path(env["MIEN_SLACK_TOKENS"])
        seen["path"] = path
        seen["existed"] = path.exists()
        seen["body"] = path.read_text() if seen["existed"] else ""
        return 0

    mocker.patch("mien.cli.subprocess.call", side_effect=fake_call)
    result = runner.invoke(main, ["exec", "demo", "--", "true"])
    assert result.exit_code == 0, result.output

    # The child really did get a plaintext credential file...
    assert seen["existed"]
    assert "xoxp-secret" in seen["body"]
    # ...and nothing survives the exec.
    assert not seen["path"].exists()
    assert list((tmp_path / "mien").iterdir()) == []


def test_exec_removes_ephemeral_files_when_child_fails(
    runner, mien_cfg, mocker, tmp_path, monkeypatch
):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    runner.invoke(main, ["init"], input="3\nmien-\n")
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.put.return_value = "ref://slack"
    runner.invoke(
        main,
        ["login", "demo", "--service", "slack", "--workspace", "acme"],
        input="y\nxoxp-secret\n",
    )

    backend.get.return_value = b"xoxp-secret"
    written: list[Path] = []

    def boom(argv, env=None):
        written.append(Path(env["MIEN_SLACK_TOKENS"]))
        raise KeyboardInterrupt

    mocker.patch("mien.cli.subprocess.call", side_effect=boom)
    result = runner.invoke(main, ["exec", "demo", "--", "true"])
    assert result.exit_code != 0
    assert written and not written[0].exists()
    assert list((tmp_path / "mien").iterdir()) == []


def test_unset_emits_unsets(runner, mien_cfg):
    runner.invoke(main, ["init"], input="3\nmien-\n")
    result = runner.invoke(main, ["unset"])
    assert "unset MIEN_PROFILE" in result.output


def test_token_google_prints_access_token(runner, mien_cfg, mocker):
    runner.invoke(main, ["init"], input="3\nmien-\n")
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.put.side_effect = ["ref://oauth", "ref://refresh"]
    backend.get.side_effect = lambda r: {
        "ref://oauth": b"csec",
        "ref://refresh": b"refresh-zzz",
    }[r]
    mocker.patch("mien.cli.google_installed_app_flow", return_value="refresh-zzz")
    mocker.patch("mien.cli.exchange_refresh_token", return_value="ya29-access")

    runner.invoke(
        main,
        ["login", "personal", "--service", "google",
         "--email", "me@x.com", "--client-id", "cid"],
        input="y\ncsec\n",
    )

    result = runner.invoke(main, ["token", "google"], env={"MIEN_PROFILE": "personal", "MIEN_CONFIG": str(mien_cfg)})
    assert result.exit_code == 0
    assert "ya29-access" in result.output


def test_token_google_accepts_explicit_profile_without_env(runner, mien_cfg, mocker, monkeypatch):
    """`mien token` must work without an ambient MIEN_PROFILE.

    AI agent harnesses (Claude Code, Codex) start a fresh shell per tool call, so
    env vars set by a previous `eval "$(mien use ...)"` are gone by the next call.
    Without an explicit --profile the agent has no reliable way to mint a token.
    """
    # CliRunner's env= overlays os.environ rather than replacing it, so an
    # exported MIEN_PROFILE on the developer's machine would otherwise mask
    # whether --profile did any work at all.
    monkeypatch.delenv("MIEN_PROFILE", raising=False)
    runner.invoke(main, ["init"], input="3\nmien-\n")
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.put.side_effect = ["ref://oauth", "ref://refresh"]
    backend.get.side_effect = lambda r: {
        "ref://oauth": b"csec",
        "ref://refresh": b"refresh-zzz",
    }[r]
    mocker.patch("mien.cli.google_installed_app_flow", return_value="refresh-zzz")
    mocker.patch("mien.cli.exchange_refresh_token", return_value="ya29-access")

    runner.invoke(
        main,
        ["login", "personal", "--service", "google",
         "--email", "me@x.com", "--client-id", "cid"],
        input="y\ncsec\n",
    )

    result = runner.invoke(
        main,
        ["token", "google", "--profile", "personal"],
        env={"MIEN_CONFIG": str(mien_cfg)},
    )
    assert result.exit_code == 0
    assert "ya29-access" in result.output


def test_token_google_explicit_profile_beats_env(runner, mien_cfg, mocker):
    """--profile must win over a conflicting ambient MIEN_PROFILE.

    The env var is only a fallback (`profile or $MIEN_PROFILE`). MIEN_PROFILE is
    pinned here to a profile that does not exist, so if --profile were ignored the
    command would fail with "not found" instead of minting the token.
    """
    runner.invoke(main, ["init"], input="3\nmien-\n")
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.put.side_effect = ["ref://oauth", "ref://refresh"]
    backend.get.side_effect = lambda r: {
        "ref://oauth": b"csec",
        "ref://refresh": b"refresh-zzz",
    }[r]
    mocker.patch("mien.cli.google_installed_app_flow", return_value="refresh-zzz")
    mocker.patch("mien.cli.exchange_refresh_token", return_value="ya29-access")

    runner.invoke(
        main,
        ["login", "personal", "--service", "google",
         "--email", "me@x.com", "--client-id", "cid"],
        input="y\ncsec\n",
    )

    result = runner.invoke(
        main,
        ["token", "google", "--profile", "personal"],
        env={"MIEN_PROFILE": "someone-else", "MIEN_CONFIG": str(mien_cfg)},
    )
    assert result.exit_code == 0, result.output
    assert "ya29-access" in result.output
    assert "someone-else" not in result.output


def test_token_without_profile_or_env_names_both_remedies(runner, mien_cfg, mocker, monkeypatch):
    """The error must name both remedies: the --profile flag and the eval pattern."""
    monkeypatch.delenv("MIEN_PROFILE", raising=False)
    runner.invoke(main, ["init"], input="3\nmien-\n")
    result = runner.invoke(main, ["token", "google"], env={"MIEN_CONFIG": str(mien_cfg)})
    assert result.exit_code != 0
    assert "--profile" in result.output
    assert "MIEN_PROFILE" in result.output
    assert 'eval "$(mien use' in result.output


def test_init_non_interactive_keychain(runner, mien_cfg, mocker):
    mocker.patch("mien.cli.load_backend").return_value.health_check.return_value = None
    result = runner.invoke(
        main,
        ["init", "--backend", "macos_keychain", "--service-prefix", "mien-"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(mien_cfg.read_text())
    assert payload["secrets_backend"]["type"] == "macos_keychain"


def test_init_non_interactive_gcp(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("mien.cli.subprocess.run")
    result = runner.invoke(
        main,
        ["init",
         "--backend", "gcp_secret_manager",
         "--project", "my-proj-1",
         "--bootstrap-email", "me@x.com"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(mien_cfg.read_text())
    assert payload["secrets_backend"]["project"] == "my-proj-1"
    assert payload["bootstrap"]["gcp_account"] == "me@x.com"


def test_init_yes_overwrites_existing(runner, mien_cfg, mocker):
    mien_cfg.parent.mkdir(parents=True, exist_ok=True)
    mien_cfg.write_text("{}")
    mocker.patch("mien.cli.load_backend").return_value.health_check.return_value = None
    result = runner.invoke(
        main,
        ["init", "-y", "--backend", "macos_keychain", "--service-prefix", "mien-"],
    )
    assert result.exit_code == 0, result.output


def test_login_github_token_stdin(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.put.return_value = "ref://gh"
    runner.invoke(main, ["init"], input="3\nmien-\n")
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "github", "--username", "me", "--token-stdin"],
        input="y\nghp_pasted_token\n",
    )
    assert result.exit_code == 0, result.output
    args = backend.put.call_args[0]
    assert args[1] == b"ghp_pasted_token"


def test_login_github_ssh_key_path_skips_pat_prompt(runner, mien_cfg, mocker, tmp_path):
    mocker.patch("mien.cli.load_backend")
    runner.invoke(main, ["init"], input="3\nmien-\n")
    keyfile = tmp_path / "id_test"
    keyfile.write_text("PRIVATE")
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "github", "--ssh-key-path", str(keyfile)],
        input="y\n",
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(mien_cfg.read_text())
    gh = payload["profiles"]["personal"]["github"]
    assert gh["ssh_key_path"] == str(keyfile)
    assert gh["token_ref"] is None
    assert gh["ssh_key_ref"] is None


def test_login_github_ssh_key_stored_in_backend(runner, mien_cfg, mocker, tmp_path):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.put.return_value = "ref://ssh"
    runner.invoke(main, ["init"], input="3\nmien-\n")
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
    payload = json.loads(mien_cfg.read_text())
    gh = payload["profiles"]["personal"]["github"]
    assert gh["ssh_key_ref"] == "ref://ssh"
    assert gh["token_ref"] is None


def test_login_github_interactive_ssh_prompt_path(runner, mien_cfg, mocker, tmp_path):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.put.return_value = "ref://gh"
    keyfile = tmp_path / "id_test"
    keyfile.write_text("PRIVATE")
    runner.invoke(main, ["init"], input="3\nmien-\n")
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "github"],
        input=f"y\nme\ntok\ny\n{keyfile}\npath\n",
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(mien_cfg.read_text())
    gh = payload["profiles"]["personal"]["github"]
    assert gh["token_ref"] == "ref://gh"
    assert gh["ssh_key_path"] == str(keyfile)
    assert gh["ssh_key_ref"] is None


def test_login_github_pat_and_ssh_compose_across_calls(runner, mien_cfg, mocker, tmp_path):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.put.return_value = "ref://gh"
    runner.invoke(main, ["init"], input="3\nmien-\n")
    runner.invoke(main, ["login", "work2", "--service", "github"], input="y\nme\ntok\nn\n")
    keyfile = tmp_path / "id_test"
    keyfile.write_text("PRIVATE")
    runner.invoke(
        main,
        ["login", "work2", "--service", "github", "--ssh-key-path", str(keyfile)],
    )
    payload = json.loads(mien_cfg.read_text())
    gh = payload["profiles"]["work2"]["github"]
    assert gh["token_ref"] == "ref://gh"
    assert gh["ssh_key_path"] == str(keyfile)


def test_preflight_keychain_passes(runner, mocker):
    # Preflight checks the real backend path (in-process Keychain), not the
    # security CLI — so a reachable Keychain is a healthy backend.
    mocker.patch("mien.backends.keychain._MacKeyring").return_value.get_password.return_value = None
    result = runner.invoke(main, ["preflight", "--backend", "macos_keychain", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["backend"] == "macos_keychain"
    assert all(c["ok"] for c in payload["checks"])
    assert any("keychain" in c["check"].lower() for c in payload["checks"])


def test_preflight_gcp_reports_missing_pieces(runner, mien_cfg, mocker):
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
    mocker.patch("mien.cli.subprocess.run", side_effect=fake_run)
    mocker.patch("mien.cli.Path.exists", return_value=False)  # ADC missing
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


def test_logout_removes_service(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.put.return_value = "ref://gh"
    runner.invoke(main, ["init"], input="3\nmien-\n")
    runner.invoke(main, ["login", "personal", "--service", "github"], input="y\nme\ntok\nn\n")
    result = runner.invoke(main, ["logout", "personal", "--service", "github"])
    assert result.exit_code == 0
    backend.delete.assert_called_with("ref://gh")
    payload = json.loads(mien_cfg.read_text())
    assert payload["profiles"]["personal"]["github"] is None


def test_doctor_runs_health_check(runner, mien_cfg, mocker):
    runner.invoke(main, ["init"], input="3\nmien-\n")
    backend = mocker.patch("mien.cli.load_backend").return_value
    result = runner.invoke(main, ["doctor"])
    assert result.exit_code == 0
    backend.health_check.assert_called_once()
    assert "OK" in result.output


def test_doctor_reports_failure(runner, mien_cfg, mocker):
    runner.invoke(main, ["init"], input="3\nmien-\n")
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.health_check.side_effect = RuntimeError("boom")
    result = runner.invoke(main, ["doctor"])
    assert result.exit_code != 0
    assert "boom" in result.output


def test_doctor_gc_sweeps(runner, mien_cfg, mocker):
    runner.invoke(main, ["init"], input="3\nmien-\n")
    mocker.patch("mien.cli.load_backend").return_value
    gc = mocker.patch("mien.cli.EphemeralStore.gc")
    runner.invoke(main, ["doctor", "--gc"])
    gc.assert_called_once()


def test_init_rejects_project_name_with_space(runner, mien_cfg):
    result = runner.invoke(main, ["init"], input="1\nMy First Project\n")
    assert result.exit_code != 0
    assert "PROJECT_ID" in result.output
    assert "gcloud projects list" in result.output
    assert not mien_cfg.exists()


def test_init_rejects_uppercase_project_id(runner, mien_cfg):
    result = runner.invoke(main, ["init"], input="1\nMy-Project\n")
    assert result.exit_code != 0
    assert "PROJECT_ID" in result.output


def test_init_strips_markdown_email(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("mien.cli.subprocess.run")  # don't touch real gcloud ADC
    result = runner.invoke(
        main,
        ["init"],
        input="1\nmy-proj-1\n[a@b.com](mailto:a@b.com)\n",
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(mien_cfg.read_text())
    assert payload["bootstrap"]["gcp_account"] == "a@b.com"


def test_init_aborts_on_health_check_failure_with_actionable_message(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.health_check.side_effect = RuntimeError("permission denied: caller lacks role")
    result = runner.invoke(main, ["init"], input="1\nmy-proj-1\nme@x.com\n")
    assert result.exit_code != 0
    out = result.output
    assert "permission denied" in out.lower()
    assert "gcloud auth application-default login --account=me@x.com" in out
    assert "mien doctor" in out
    # Config should still be on disk so user can fix without re-prompting.
    assert mien_cfg.exists()


def test_init_keychain_runs_health_check(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.health_check.return_value = None
    result = runner.invoke(main, ["init"], input="3\nmien-\n")
    assert result.exit_code == 0
    backend.health_check.assert_called_once()
    assert "OK" in result.output


def test_init_sets_quota_project_for_gcp(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.health_check.return_value = None
    sub = mocker.patch("mien.cli.subprocess.run")
    result = runner.invoke(main, ["init"], input="1\nsayu-studio\nme@x.com\n")
    assert result.exit_code == 0, result.output
    quota_calls = [
        c for c in sub.call_args_list
        if c[0][0][:4] == ["gcloud", "auth", "application-default", "set-quota-project"]
    ]
    assert len(quota_calls) == 1
    assert quota_calls[0][0][0][4] == "sayu-studio"
    assert "quota project to sayu-studio" in result.output


def test_init_warns_when_quota_project_set_fails(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("mien.cli.subprocess.run", side_effect=FileNotFoundError("gcloud"))
    result = runner.invoke(main, ["init"], input="1\nsayu-studio\nme@x.com\n")
    assert result.exit_code == 0
    assert "could not set ADC quota project" in result.output
    assert "gcloud auth application-default set-quota-project sayu-studio" in result.output


def test_login_google_shows_oauth_hint_when_client_id_missing(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.health_check.return_value = None
    backend.put.side_effect = ["ref://oauth", "ref://refresh"]
    mocker.patch("mien.cli.google_installed_app_flow", return_value="refresh-zzz")
    mocker.patch("mien.cli.subprocess.run")  # set-quota-project no-op
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


def test_login_google_skips_hint_when_client_id_provided(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.health_check.return_value = None
    backend.put.side_effect = ["ref://oauth", "ref://refresh"]
    mocker.patch("mien.cli.google_installed_app_flow", return_value="refresh-zzz")
    mocker.patch("mien.cli.subprocess.run")
    runner.invoke(main, ["init"], input="1\nsayu-studio\nme@x.com\n")
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "google",
         "--email", "me@x.com", "--client-id", "cid"],
        input="y\ncsec\n",
    )
    assert result.exit_code == 0, result.output
    assert "OAuth Desktop client" not in result.output


def test_login_github_pushes_manifest(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.put.return_value = "ref://gh-token"
    mocker.patch("mien.cli.pull_manifest", return_value=None)
    push = mocker.patch("mien.cli.push_manifest")
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


def test_login_manifest_push_failure_is_nonfatal(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.put.return_value = "ref://gh-token"
    mocker.patch("mien.cli.pull_manifest", return_value=None)
    mocker.patch("mien.cli.push_manifest", side_effect=RuntimeError("network down"))
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


def test_login_keychain_does_not_push_manifest(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.put.return_value = "ref://gh-token"
    push = mocker.patch("mien.cli.push_manifest")
    runner.invoke(main, ["init"], input="3\nmien-\n")
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "github"],
        input="y\nmyuser\nghp_token123\nn\n",
    )
    assert result.exit_code == 0, result.output
    push.assert_not_called()


def test_logout_pushes_manifest(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.put.return_value = "ref://gh"
    mocker.patch("mien.cli.pull_manifest", return_value=None)
    push = mocker.patch("mien.cli.push_manifest")
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


def test_login_rejects_reserved_manifest_profile_name(runner, mien_cfg, mocker):
    mocker.patch("mien.cli.load_backend")
    runner.invoke(main, ["init"], input="3\nmien-\n")
    result = runner.invoke(
        main,
        ["login", "mien-config-manifest", "--service", "github", "--username", "u"],
        input="y\n",
    )
    assert result.exit_code != 0
    assert "reserved" in result.output.lower()


def _manifest_cfg():
    from mien.config import (BackendConfig, Config, GitHubService, Profile,
                            SecretNaming)
    return Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="gcp_secret_manager", options={"project": "p1"}),
        bootstrap={"gcp_account": "me@x.com"},
        secret_naming=SecretNaming(default="mien-{profile}-{service}-{kind}",
                                   slack_token="mien-{profile}-slack-{workspace}-token"),
        profiles={"work": Profile(name="work",
                                  github=GitHubService(username="u", host="github.com",
                                                       token_ref="ref://x"))},
    )


def test_init_offers_and_imports_manifest(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("mien.cli.subprocess.run")
    mocker.patch("mien.cli.pull_manifest", return_value=_manifest_cfg())
    result = runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
        input="y\n",
    )
    assert result.exit_code == 0, result.output
    assert "Imported 1 profiles" in result.output
    payload = json.loads(mien_cfg.read_text())
    assert "work" in payload["profiles"]


def test_init_no_import_flag_skips_manifest(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("mien.cli.subprocess.run")
    mocker.patch("mien.cli.pull_manifest", return_value=_manifest_cfg())
    result = runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager", "--no-import",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(mien_cfg.read_text())
    assert payload["profiles"] == {}


def test_init_keychain_never_pulls_manifest(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.health_check.return_value = None
    pull = mocker.patch("mien.cli.pull_manifest")
    result = runner.invoke(main, ["init"], input="3\nmien-\n")
    assert result.exit_code == 0, result.output
    pull.assert_not_called()


def test_init_user_declines_manifest_import(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("mien.cli.subprocess.run")
    mocker.patch("mien.cli.pull_manifest", return_value=_manifest_cfg())
    result = runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
        input="n\n",
    )
    assert result.exit_code == 0, result.output
    assert "Next:" in result.output
    payload = json.loads(mien_cfg.read_text())
    assert payload["profiles"] == {}


def test_sync_dry_run_reports_diff_and_writes_nothing(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("mien.cli.subprocess.run")
    mocker.patch("mien.cli.pull_manifest", return_value=None)
    runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager", "--no-import",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    before = mien_cfg.read_text()
    mocker.patch("mien.cli.pull_manifest", return_value=_manifest_cfg())
    result = runner.invoke(main, ["sync", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "+ add:" in result.output and "work" in result.output
    assert mien_cfg.read_text() == before  # unchanged


def test_sync_applies_with_yes(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("mien.cli.subprocess.run")
    mocker.patch("mien.cli.pull_manifest", return_value=None)
    runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager", "--no-import",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    mocker.patch("mien.cli.pull_manifest", return_value=_manifest_cfg())
    result = runner.invoke(main, ["sync", "-y"])
    assert result.exit_code == 0, result.output
    payload = json.loads(mien_cfg.read_text())
    assert "work" in payload["profiles"]


def test_sync_no_manifest_errors(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("mien.cli.subprocess.run")
    mocker.patch("mien.cli.pull_manifest", return_value=None)
    runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager", "--no-import",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    result = runner.invoke(main, ["sync"])
    assert result.exit_code != 0
    assert "no manifest" in result.output.lower()


def test_sync_requires_cloud_backend(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.health_check.return_value = None
    runner.invoke(main, ["init"], input="3\nmien-\n")
    result = runner.invoke(main, ["sync"])
    assert result.exit_code != 0
    assert "cloud backend" in result.output.lower()


def test_sync_already_in_sync(runner, mien_cfg, mocker):
    import mien.config as miencfg
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("mien.cli.subprocess.run")
    mocker.patch("mien.cli.pull_manifest", return_value=None)
    runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager", "--no-import",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    # make local config identical to the manifest we'll pull
    mien_cfg.write_text(miencfg.serialize_config(_manifest_cfg()))
    mocker.patch("mien.cli.pull_manifest", return_value=_manifest_cfg())
    result = runner.invoke(main, ["sync"])
    assert result.exit_code == 0, result.output
    assert "already in sync" in result.output


def test_sync_user_declines_confirm_aborts(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("mien.cli.subprocess.run")
    mocker.patch("mien.cli.pull_manifest", return_value=None)
    runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager", "--no-import",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    before = mien_cfg.read_text()
    mocker.patch("mien.cli.pull_manifest", return_value=_manifest_cfg())
    result = runner.invoke(main, ["sync"], input="n\n")
    assert result.exit_code != 0
    assert mien_cfg.read_text() == before  # nothing written


def test_push_command_pushes_manifest(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    mocker.patch("mien.cli.subprocess.run")
    mocker.patch("mien.cli.pull_manifest", return_value=None)
    runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager", "--no-import",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    push = mocker.patch("mien.cli.push_manifest")
    result = runner.invoke(main, ["push"])
    assert result.exit_code == 0, result.output
    push.assert_called_once()
    assert "pushed config manifest" in result.output


def test_push_command_noop_on_keychain(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.health_check.return_value = None
    runner.invoke(main, ["init"], input="3\nmien-\n")
    push = mocker.patch("mien.cli.push_manifest")
    result = runner.invoke(main, ["push"])
    assert result.exit_code == 0, result.output
    push.assert_not_called()
    assert "no-op" in result.output.lower()


def test_init_yes_auto_imports_manifest_without_prompt(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("mien.cli.subprocess.run")
    mocker.patch("mien.cli.pull_manifest", return_value=_manifest_cfg())
    result = runner.invoke(
        main,
        ["init", "-y", "--backend", "gcp_secret_manager",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    assert result.exit_code == 0, result.output
    assert "Imported 1 profiles" in result.output
    payload = json.loads(mien_cfg.read_text())
    assert "work" in payload["profiles"]


def test_login_atlassian_stores_token_and_updates_config(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.put.return_value = "ref://atl-token"
    runner.invoke(main, ["init"], input="3\nmien-\n")
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
    payload = json.loads(mien_cfg.read_text())
    atl = payload["profiles"]["personal"]["atlassian"]
    assert atl["email"] == "me@company.com"
    assert atl["base_url"] == "https://company.atlassian.net"
    assert atl["api_token_ref"] == "ref://atl-token"


def test_list_shows_atlassian(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.put.return_value = "ref://atl-token"
    runner.invoke(main, ["init"], input="3\nmien-\n")
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


def test_logout_atlassian_removes_service(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.put.return_value = "ref://atl-token"
    runner.invoke(main, ["init"], input="3\nmien-\n")
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
    payload = json.loads(mien_cfg.read_text())
    assert payload["profiles"]["personal"]["atlassian"] is None


def test_token_atlassian_prints_api_token(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.put.return_value = "ref://atl-token"
    backend.get.return_value = b"my-secret-api-token"
    runner.invoke(main, ["init"], input="3\nmien-\n")
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
        env={"MIEN_PROFILE": "personal", "MIEN_CONFIG": str(mien_cfg)},
    )
    assert result.exit_code == 0, result.output
    assert "my-secret-api-token" in result.output


def test_login_notion_stores_token_and_updates_config(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.put.return_value = "ref://notion-token"
    runner.invoke(main, ["init"], input="3\nmien-\n")
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "notion", "--token-stdin"],
        input="y\nmy-notion-token\n",
    )
    assert result.exit_code == 0, result.output
    assert "stored notion identity" in result.output
    payload = json.loads(mien_cfg.read_text())
    assert payload["profiles"]["personal"]["notion"]["api_token_ref"] == "ref://notion-token"


def test_list_shows_notion(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.put.return_value = "ref://notion-token"
    runner.invoke(main, ["init"], input="3\nmien-\n")
    runner.invoke(
        main,
        ["login", "personal", "--service", "notion", "--token-stdin"],
        input="y\nmy-notion-token\n",
    )
    result = runner.invoke(main, ["list"])
    assert result.exit_code == 0, result.output
    assert "notion" in result.output


def test_logout_notion_removes_service(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.put.return_value = "ref://notion-token"
    runner.invoke(main, ["init"], input="3\nmien-\n")
    runner.invoke(
        main,
        ["login", "personal", "--service", "notion", "--token-stdin"],
        input="y\nmy-notion-token\n",
    )
    result = runner.invoke(main, ["logout", "personal", "--service", "notion"])
    assert result.exit_code == 0, result.output
    backend.delete.assert_called_with("ref://notion-token")
    payload = json.loads(mien_cfg.read_text())
    assert payload["profiles"]["personal"]["notion"] is None


def test_token_notion_prints_api_token(runner, mien_cfg, mocker):
    backend = mocker.patch("mien.cli.load_backend").return_value
    backend.put.return_value = "ref://notion-token"
    backend.get.return_value = b"my-secret-notion-token"
    runner.invoke(main, ["init"], input="3\nmien-\n")
    runner.invoke(
        main,
        ["login", "personal", "--service", "notion", "--token-stdin"],
        input="y\nmy-secret-notion-token\n",
    )
    result = runner.invoke(
        main, ["token", "notion"],
        env={"MIEN_PROFILE": "personal", "MIEN_CONFIG": str(mien_cfg)},
    )
    assert result.exit_code == 0, result.output
    assert "my-secret-notion-token" in result.output


def _pinned_config(tmp_path, monkeypatch, **scopes):
    """Write a config whose profiles claim directories via default_for."""
    from mien.config import BackendConfig, Config, Profile, SecretNaming, save_config
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "config.json"))
    save_config(Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={}, secret_naming=SecretNaming(default="d", slack_token="s"),
        profiles={n: Profile(name=n, default_for=list(g)) for n, g in scopes.items()},
    ))


def test_which_resolves_profile_from_cwd(runner, tmp_path, monkeypatch):
    work = tmp_path / "Projects" / "acme" / "src"
    work.mkdir(parents=True)
    _pinned_config(tmp_path, monkeypatch, work=["*/Projects/acme"])
    monkeypatch.delenv("MIEN_PROFILE", raising=False)
    monkeypatch.chdir(work)
    result = runner.invoke(main, ["which"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "work"


def test_which_resolves_through_a_symlinked_path_via_pwd(runner, tmp_path, monkeypatch):
    """`os.getcwd()` resolves symlinks and the shell's `$PWD` does not, so a scope
    the generated `case "$PWD/" in ...` matches must match here too — otherwise the
    same directory has an ambient env from one profile and no identity at all."""
    (tmp_path / "real" / "acme").mkdir(parents=True)
    (tmp_path / "Projects").symlink_to(tmp_path / "real")
    logical = tmp_path / "Projects" / "acme"
    _pinned_config(tmp_path, monkeypatch, work=["*/Projects/acme"])
    monkeypatch.delenv("MIEN_PROFILE", raising=False)
    monkeypatch.chdir(logical)
    assert "/Projects/" not in os.getcwd()      # the physical path really differs
    monkeypatch.setenv("PWD", str(logical))     # what the shell reports there
    result = runner.invoke(main, ["which"])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "work"


def test_which_ignores_a_pwd_naming_a_different_directory(runner, tmp_path, monkeypatch):
    """`PWD` is inherited and goes stale in any subprocess that chdir'd. Trusting
    it past `samefile` would hand out another project's credentials."""
    here = tmp_path / "elsewhere"
    here.mkdir()
    claimed = tmp_path / "Projects" / "acme"
    claimed.mkdir(parents=True)
    _pinned_config(tmp_path, monkeypatch, work=["*/Projects/acme"])
    monkeypatch.delenv("MIEN_PROFILE", raising=False)
    monkeypatch.chdir(here)
    monkeypatch.setenv("PWD", str(claimed))     # a real directory, but not this one
    result = runner.invoke(main, ["which"])
    assert result.exit_code != 0
    assert result.stdout.strip() == ""


def test_which_falls_back_to_getcwd_when_pwd_is_unusable(runner, tmp_path, monkeypatch):
    work = tmp_path / "Projects" / "acme"
    work.mkdir(parents=True)
    _pinned_config(tmp_path, monkeypatch, work=["*/Projects/acme"])
    monkeypatch.delenv("MIEN_PROFILE", raising=False)
    monkeypatch.chdir(work)

    monkeypatch.setenv("PWD", "/no/such/directory/anywhere")   # points nowhere
    assert runner.invoke(main, ["which"]).stdout.strip() == "work"

    monkeypatch.setenv("PWD", "not/absolute")                  # not a real cwd
    assert runner.invoke(main, ["which"]).stdout.strip() == "work"

    monkeypatch.delenv("PWD", raising=False)                   # unset entirely
    assert runner.invoke(main, ["which"]).stdout.strip() == "work"


def test_which_exits_nonzero_with_no_output_when_unclaimed(runner, tmp_path, monkeypatch):
    """Callers substitute this into other commands, so an unresolved directory
    must not print a profile name that would then be used."""
    loose = tmp_path / "elsewhere"
    loose.mkdir()
    _pinned_config(tmp_path, monkeypatch, work=["*/Projects/acme"])
    monkeypatch.delenv("MIEN_PROFILE", raising=False)
    monkeypatch.chdir(loose)
    result = runner.invoke(main, ["which"])
    assert result.exit_code != 0
    assert result.stdout.strip() == ""


def test_which_prefers_an_explicitly_activated_profile(runner, tmp_path, monkeypatch):
    """Someone who ran `mien use` said what they wanted; a directory default
    must not silently override a deliberate act."""
    work = tmp_path / "Projects" / "acme"
    work.mkdir(parents=True)
    _pinned_config(tmp_path, monkeypatch, work=["*/Projects/acme"], personal=[])
    monkeypatch.setenv("MIEN_PROFILE", "personal")
    monkeypatch.chdir(work)
    result = runner.invoke(main, ["which"])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "personal"


def test_which_rejects_an_active_profile_absent_from_config(runner, tmp_path, monkeypatch):
    """MIEN_PROFILE is an arbitrary string — a renamed or deleted profile leaves a
    stale one exported. `which` feeds other commands, so a name that resolves to
    nothing must fail here rather than downstream, and stdout must stay empty."""
    work = tmp_path / "Projects" / "acme"
    work.mkdir(parents=True)
    _pinned_config(tmp_path, monkeypatch, work=["*/Projects/acme"])
    monkeypatch.setenv("MIEN_PROFILE", "deleted-profile")
    monkeypatch.chdir(work)
    result = runner.invoke(main, ["which"])
    assert result.exit_code != 0
    assert "deleted-profile" in result.output
    assert "not found" in result.output
    assert result.stdout.strip() == ""


def test_which_warns_when_active_profile_contradicts_the_directory(runner, tmp_path, monkeypatch):
    """The override is honoured, but silently acting against the directory's
    default is exactly the confusion this feature exists to remove."""
    work = tmp_path / "Projects" / "acme"
    work.mkdir(parents=True)
    _pinned_config(tmp_path, monkeypatch, work=["*/Projects/acme"], personal=[])
    monkeypatch.setenv("MIEN_PROFILE", "personal")
    monkeypatch.chdir(work)
    result = runner.invoke(main, ["which"], catch_exceptions=False)
    assert "work" in result.stderr
    assert result.stdout.strip() == "personal"


def test_which_refuses_to_guess_between_equally_specific_scopes(runner, tmp_path, monkeypatch):
    shared = tmp_path / "Projects" / "shared"
    shared.mkdir(parents=True)
    _pinned_config(tmp_path, monkeypatch,
                   alpha=["*/Projects/shared"], bravo=["*/Projects/shared"])
    monkeypatch.delenv("MIEN_PROFILE", raising=False)
    monkeypatch.chdir(shared)
    result = runner.invoke(main, ["which"])
    assert result.exit_code != 0
    assert "claimed with equal specificity by: alpha, bravo" in result.output


def test_which_prefers_an_activated_profile_over_an_ambiguous_directory(
    runner, tmp_path, monkeypatch
):
    """An explicit `mien use` leaves nothing to guess, so a directory two
    profiles claim equally must not abort the command."""
    shared = tmp_path / "Projects" / "shared"
    shared.mkdir(parents=True)
    _pinned_config(tmp_path, monkeypatch,
                   alpha=["*/Projects/shared"], bravo=["*/Projects/shared"],
                   personal=[])
    monkeypatch.setenv("MIEN_PROFILE", "personal")
    monkeypatch.chdir(shared)
    result = runner.invoke(main, ["which"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "personal"


def test_which_warns_when_the_directory_is_ambiguous_under_an_override(
    runner, tmp_path, monkeypatch
):
    """Proceeding under the override is right, but the clashing scopes are a
    real misconfiguration the user should hear about."""
    shared = tmp_path / "Projects" / "shared"
    shared.mkdir(parents=True)
    _pinned_config(tmp_path, monkeypatch,
                   alpha=["*/Projects/shared"], bravo=["*/Projects/shared"],
                   personal=[])
    monkeypatch.setenv("MIEN_PROFILE", "personal")
    monkeypatch.chdir(shared)
    result = runner.invoke(main, ["which"], catch_exceptions=False)
    assert "claimed by several profiles with equal specificity" in result.stderr
    assert "using 'personal'" in result.stderr
    assert result.stdout.strip() == "personal"


def test_run_uses_the_activated_profile_when_the_directory_is_ambiguous(
    runner, tmp_path, monkeypatch, mocker
):
    shared = tmp_path / "Projects" / "shared"
    shared.mkdir(parents=True)
    _pinned_config(tmp_path, monkeypatch,
                   alpha=["*/Projects/shared"], bravo=["*/Projects/shared"],
                   personal=[])
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setenv("MIEN_PROFILE", "personal")
    monkeypatch.chdir(shared)
    mocker.patch("mien.cli.load_backend")
    called = mocker.patch("mien.cli.subprocess.call", return_value=0)

    result = runner.invoke(main, ["run", "--", "printenv", "MIEN_PROFILE"])
    assert result.exit_code == 0, result.output
    assert called.call_args.kwargs["env"]["MIEN_PROFILE"] == "personal"


def test_run_executes_under_the_directory_profile(runner, tmp_path, monkeypatch, mocker):
    work = tmp_path / "Projects" / "acme"
    work.mkdir(parents=True)
    _pinned_config(tmp_path, monkeypatch, work=["*/Projects/acme"])
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.delenv("MIEN_PROFILE", raising=False)
    monkeypatch.chdir(work)
    mocker.patch("mien.cli.load_backend")
    called = mocker.patch("mien.cli.subprocess.call", return_value=0)

    result = runner.invoke(main, ["run", "--", "printenv", "MIEN_PROFILE"])
    assert result.exit_code == 0, result.output
    assert called.call_args.args[0] == ["printenv", "MIEN_PROFILE"]
    assert called.call_args.kwargs["env"]["MIEN_PROFILE"] == "work"


def test_run_honours_an_inherited_profile_over_the_directory(runner, tmp_path, monkeypatch, mocker):
    """The child must run as the activated profile, not the directory's.

    An agent session launched from a terminal where someone ran `mien-use work`
    inherits MIEN_PROFILE into every command, so this is the routine case, not an
    exotic one — SKILL.md says so and the whole override contract rests on it.
    Pinned here because it was not: making `run` alone prefer the directory left
    the entire suite green while inverting credential routing for those sessions.
    """
    pinned = tmp_path / "Projects" / "acme"
    pinned.mkdir(parents=True)
    _pinned_config(tmp_path, monkeypatch, work=["*/Projects/acme"], personal=[])
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setenv("MIEN_PROFILE", "personal")
    monkeypatch.chdir(pinned)
    mocker.patch("mien.cli.load_backend")
    called = mocker.patch("mien.cli.subprocess.call", return_value=0)

    result = runner.invoke(main, ["run", "--", "true"])
    assert result.exit_code == 0, result.output
    # The directory says 'work'; the activated profile must still win.
    assert called.call_args.kwargs["env"]["MIEN_PROFILE"] == "personal"


def test_run_lets_the_profile_override_the_ambient_environment(runner, tmp_path, monkeypatch, mocker):
    """The profile must win the merge, not the shell it was launched from.

    `_run_as_profile` builds the child env as {**os.environ, **bundle.env}. If
    that order were ever reversed, a shell already carrying GH_TOKEN from an
    earlier `mien use` would hand the child THAT token while the child still
    reports the requested profile — a silent cross-identity leak, and the exact
    failure this tool exists to prevent. Nothing pinned the order before.
    """
    work = tmp_path / "Projects" / "acme"
    work.mkdir(parents=True)
    _pinned_config(tmp_path, monkeypatch, work=["*/Projects/acme"])
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.delenv("MIEN_PROFILE", raising=False)
    # A stale value from some earlier activation, still exported in this shell.
    monkeypatch.setenv("MIEN_EPHEMERAL_DIR", "/stale/from/an/earlier/shell")
    monkeypatch.chdir(work)
    mocker.patch("mien.cli.load_backend")
    called = mocker.patch("mien.cli.subprocess.call", return_value=0)

    result = runner.invoke(main, ["run", "--", "true"])
    assert result.exit_code == 0, result.output
    child_env = called.call_args.kwargs["env"]
    # build_env sets MIEN_EPHEMERAL_DIR; the profile's value must displace the
    # ambient one rather than the other way round.
    assert child_env["MIEN_EPHEMERAL_DIR"] != "/stale/from/an/earlier/shell"
    assert child_env["MIEN_PROFILE"] == "work"
    # Ambient values the profile does NOT define still pass through.
    assert child_env["TMPDIR"] == str(tmp_path)


def test_run_rejects_a_stale_active_profile(runner, tmp_path, monkeypatch, mocker):
    """`run` indexes cfg.profiles[name] directly, on the strength of the check in
    _resolve_cwd_profile. If that check ever moves, this fails loudly here rather
    than as a KeyError traceback."""
    work = tmp_path / "Projects" / "acme"
    work.mkdir(parents=True)
    _pinned_config(tmp_path, monkeypatch, work=["*/Projects/acme"])
    monkeypatch.setenv("MIEN_PROFILE", "deleted-profile")
    monkeypatch.chdir(work)
    called = mocker.patch("mien.cli.subprocess.call", return_value=0)

    result = runner.invoke(main, ["run", "--", "true"])
    assert result.exit_code != 0
    assert "deleted-profile" in result.output
    assert "not found" in result.output
    called.assert_not_called()


def test_run_refuses_an_ambiguous_directory_without_an_override(runner, tmp_path, monkeypatch, mocker):
    """Only the override variant was pinned; the refusal itself was not."""
    shared = tmp_path / "Projects" / "shared"
    shared.mkdir(parents=True)
    _pinned_config(tmp_path, monkeypatch,
                   alpha=["*/Projects/shared"], bravo=["*/Projects/shared"])
    monkeypatch.delenv("MIEN_PROFILE", raising=False)
    monkeypatch.chdir(shared)
    called = mocker.patch("mien.cli.subprocess.call", return_value=0)

    result = runner.invoke(main, ["run", "--", "true"])
    assert result.exit_code != 0
    assert "claimed with equal specificity by: alpha, bravo" in result.output
    called.assert_not_called()


def test_run_removes_ephemeral_files_after_child_exits(runner, tmp_path, monkeypatch, mocker):
    """`run` spawns the child, so like `exec` it owns the plaintext credential
    files build_env writes — and no shell EXIT trap sweeps them on this path."""
    from mien.config import (BackendConfig, Config, Profile, SecretNaming,
                             SlackWorkspace, save_config)
    work = tmp_path / "Projects" / "acme"
    work.mkdir(parents=True)
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.delenv("MIEN_PROFILE", raising=False)
    save_config(Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={}, secret_naming=SecretNaming(default="d", slack_token="s"),
        profiles={"work": Profile(
            name="work",
            default_for=["*/Projects/acme"],
            slack=[SlackWorkspace(workspace="team-a", team_id=None,
                                  user_token_ref="ref://slack")],
        )},
    ))
    mocker.patch("mien.cli.load_backend").return_value.get.return_value = b"xoxp-secret"
    monkeypatch.chdir(work)

    seen = {}

    def fake_call(argv, env=None, **kw):
        # The file must exist WHILE the child runs, or this test would pass
        # vacuously against a build_env that wrote nothing.
        seen["path"] = env["MIEN_SLACK_TOKENS"]
        seen["body"] = Path(env["MIEN_SLACK_TOKENS"]).read_text()
        return 0

    mocker.patch("mien.cli.subprocess.call", side_effect=fake_call)
    result = runner.invoke(main, ["run", "--", "true"])
    assert result.exit_code == 0, result.output
    assert "xoxp-secret" in seen["body"]
    assert not Path(seen["path"]).exists()
    assert list((tmp_path / "mien").iterdir()) == []


def test_run_names_the_remedy_when_the_directory_is_unclaimed(runner, tmp_path, monkeypatch):
    loose = tmp_path / "elsewhere"
    loose.mkdir()
    _pinned_config(tmp_path, monkeypatch, work=["*/Projects/acme"])
    monkeypatch.delenv("MIEN_PROFILE", raising=False)
    monkeypatch.chdir(loose)
    result = runner.invoke(main, ["run", "--", "true"])
    assert result.exit_code != 0
    assert "default_for" in result.output or "mien exec" in result.output


def test_env_sync_writes_ambient_and_wires_zshenv(monkeypatch, tmp_path):
    from click.testing import CliRunner
    from mien.cli import main
    from mien.config import (Config, BackendConfig, SecretNaming, Profile,
                             ProjectEnvScope, save_config)
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "config.json"))
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


def _env_sync_with_scope(monkeypatch, tmp_path, scope):
    from click.testing import CliRunner
    from mien.cli import main
    from mien.config import (Config, BackendConfig, SecretNaming, Profile,
                             ProjectEnvScope, save_config)
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("HOME", str(tmp_path))
    save_config(Config(schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={}, secret_naming=SecretNaming(default="d", slack_token="s"),
        profiles={"work": Profile(name="work", project_env=[
            ProjectEnvScope(match=scope, env={"AWS_PROFILE": "work"})])}))
    return CliRunner().invoke(main, ["env", "sync"])


def test_env_sync_warns_when_a_scope_variable_is_unset_in_zshenv(monkeypatch, tmp_path):
    # "$WORK_ROOT/$TEAM/*" is empty in ~/.zshenv (read before ~/.zshrc), so the
    # emitted pattern collapses to "//*" and AWS_PROFILE would be exported
    # everywhere.
    #
    # Two variables, deliberately: the message also echoes the scope verbatim, so
    # asserting on "$WORK_ROOT" alone passes even if the rendered reference list is
    # garbage. The contiguous "$WORK_ROOT, $TEAM" appears nowhere in the scope text
    # ("$WORK_ROOT/$TEAM/*"), so only the list itself can put it on stderr.
    res = _env_sync_with_scope(monkeypatch, tmp_path, "$WORK_ROOT/$TEAM/*")
    assert res.exit_code == 0, res.output
    assert "$WORK_ROOT, $TEAM" in res.stderr             # every offender, in order,
    assert "$WORK_ROOT" in res.stderr                    # each rendered as a reference
    assert "'work'" in res.stderr                        # names the profile
    assert "~/.zshenv" in res.stderr and "~/.zshrc" in res.stderr    # says why
    assert "literal path" in res.stderr                  # says what to do
    assert "warning" in res.stderr
    # warned, not rejected: the file is still written, unchanged by the check
    ambient = (tmp_path / "config.json").parent / "ambient.zsh"
    assert 'case "$PWD/" in $WORK_ROOT/$TEAM/*)' in ambient.read_text()
    assert 'export AWS_PROFILE="work"' in ambient.read_text()


@pytest.mark.parametrize("scope", ["~/Projects/acme", "$HOME/Projects/acme",
                                   "*/work/arinyaho"])
def test_env_sync_is_silent_for_scopes_that_survive_zshenv(monkeypatch, tmp_path, scope):
    res = _env_sync_with_scope(monkeypatch, tmp_path, scope)
    assert res.exit_code == 0, res.output
    assert "warning" not in res.stderr and "~/.zshrc" not in res.stderr
    ambient = (tmp_path / "config.json").parent / "ambient.zsh"
    assert f'case "$PWD/" in {scope}/*)' in ambient.read_text()
