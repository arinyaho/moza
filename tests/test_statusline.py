import json

from click.testing import CliRunner

from mien.cli import main
from mien.config import (BackendConfig, Config, Profile, SecretNaming,
                         save_config)
from mien.statusline import guard_reason, render_segment


class TestGuardReason:
    def test_active_identity_mismatch_blocks(self):
        r = guard_reason("personal", "work", source="repo")
        assert r and "personal" in r and "work" in r and "belongs to work" in r

    def test_wrong_git_author_blocks_even_with_nothing_active(self):
        r = guard_reason(None, "work", source="repo", author_profile="personal")
        assert r and "authored as personal" in r and "work" in r

    def test_author_mismatch_blocks_even_when_active_profile_is_right(self):
        r = guard_reason("work", "work", source="repo", author_profile="personal")
        assert r and "authored as personal" in r

    def test_everything_agrees_allows(self):
        assert guard_reason("work", "work", source="repo", author_profile="work") is None

    def test_nothing_claims_the_place_allows(self):
        assert guard_reason("personal", None, author_profile="personal") is None

    def test_a_stale_unknown_active_profile_does_not_block(self):
        # env_known=False → we can't say who you are, so we don't refuse.
        assert guard_reason("ghost", "work", source="repo", env_known=False) is None

    def test_an_unrecognized_author_does_not_block(self):
        assert guard_reason(None, "work", source="repo", author_profile=None) is None


class TestRenderSegment:
    def test_env_and_dir_agree_is_calm(self):
        assert "🟢" in render_segment("work", "work")
        assert "mien:work" in render_segment("work", "work")

    def test_env_set_dir_unclaimed_is_calm(self):
        # An explicit MIEN_PROFILE with no directory objection is a known identity.
        out = render_segment("work", None)
        assert "🟢" in out and "mien:work" in out

    def test_dir_pins_with_no_env_is_calm(self):
        out = render_segment(None, "work")
        assert "🟢" in out and "mien:work" in out

    def test_env_disagrees_with_dir_is_alarm(self):
        # The core catch: set to personal, standing in a work directory.
        out = render_segment("personal", "work")
        assert "🔴" in out
        assert "personal" in out and "work" in out
        assert "✗" in out and "dir wants work" in out

    def test_env_disagrees_with_repo_is_alarm_with_repo_wording(self):
        # Same catch, but the claim came from the git remote owner.
        out = render_segment("personal", "work", source="repo")
        assert "🔴" in out and "repo is work's" in out

    def test_ambiguous_without_env_is_alarm(self):
        out = render_segment(None, None, ambiguous=True)
        assert "🔴" in out and "ambiguous" in out

    def test_ambiguous_dir_is_calm_when_env_breaks_the_tie(self):
        # An explicit profile resolves the ambiguity, exactly as `mien run` does.
        out = render_segment("work", None, ambiguous=True)
        assert "🟢" in out and "mien:work" in out

    def test_stale_unknown_env_profile_is_alarm(self):
        out = render_segment("ghost", None, env_unknown=True)
        assert "🔴" in out and "ghost" in out and "unknown" in out

    def test_wrong_git_author_is_alarm_even_with_nothing_active(self):
        # Nothing activated, but the repo is work's and you'd commit as personal.
        out = render_segment(None, "work", source="repo", author_profile="personal")
        assert "🔴" in out and "author:personal" in out and "repo is work's" in out

    def test_right_author_raises_no_alarm(self):
        out = render_segment(None, "work", source="repo", author_profile="work")
        assert "🟢" in out and "mien:work" in out

    def test_unknown_author_does_not_nag(self):
        # author_profile is None (email matched no profile) → no author alarm.
        out = render_segment(None, "work", source="repo", author_profile=None)
        assert "🟢" in out and "mien:work" in out

    def test_env_mismatch_takes_precedence_over_author_mismatch(self):
        out = render_segment("personal", "work", source="repo", author_profile="personal")
        assert "🔴" in out and "mien:personal" in out and "repo is work's" in out

    def test_author_alarm_fires_even_when_the_active_profile_is_right(self):
        # Correctly activated work, but user.email is still personal's — stale git config.
        out = render_segment("work", "work", source="repo", author_profile="personal")
        assert "🔴" in out and "author:personal" in out

    def test_nothing_set_and_nothing_claims_is_neutral(self):
        out = render_segment(None, None)
        assert "🟡" in out and "no profile here" in out


def _write_cfg(tmp_path, monkeypatch, **profiles):
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "config.json"))
    save_config(Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={}, secret_naming=SecretNaming(default="d", slack_token="s"),
        profiles={name: Profile(name=name, default_for=scopes)
                  for name, scopes in profiles.items()},
    ))


def _write_cfg_remotes(tmp_path, monkeypatch, **owns):
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "config.json"))
    save_config(Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={}, secret_naming=SecretNaming(default="d", slack_token="s"),
        profiles={name: Profile(name=name, owns_remotes=pats)
                  for name, pats in owns.items()},
    ))


def _run(cwd, monkeypatch, mien_profile=None, remote=None, author_email=None):
    if mien_profile is None:
        monkeypatch.delenv("MIEN_PROFILE", raising=False)
    else:
        monkeypatch.setenv("MIEN_PROFILE", mien_profile)
    # Mock the git I/O so directory-based tests never shell out; remote/author
    # tests supply a fixed origin and commit email.
    monkeypatch.setattr("mien.cli.git_origin_remote", lambda _cwd: remote)
    monkeypatch.setattr("mien.cli.git_author_email", lambda _cwd: author_email)
    payload = json.dumps({"workspace": {"current_dir": cwd}})
    return CliRunner().invoke(main, ["statusline"], input=payload)


def test_statusline_shows_the_directory_profile(tmp_path, monkeypatch):
    _write_cfg(tmp_path, monkeypatch, work=["*/acme/*"], personal=["*/me/*"])
    result = _run("/w/acme/repo", monkeypatch)
    assert result.exit_code == 0
    assert "🟢" in result.output and "mien:work" in result.output


def test_statusline_flags_the_mismatch(tmp_path, monkeypatch):
    """The heart-racing case: personal is active, but this directory is work's."""
    _write_cfg(tmp_path, monkeypatch, work=["*/acme/*"], personal=["*/me/*"])
    result = _run("/w/acme/repo", monkeypatch, mien_profile="personal")
    assert result.exit_code == 0
    assert "🔴" in result.output
    assert "personal" in result.output and "work" in result.output


def test_statusline_neutral_when_no_scope_claims_the_dir(tmp_path, monkeypatch):
    _write_cfg(tmp_path, monkeypatch, work=["*/acme/*"])
    result = _run("/tmp/somewhere-else", monkeypatch)
    assert result.exit_code == 0
    assert "🟡" in result.output and "no profile here" in result.output


def test_statusline_shows_pending_for_an_unapproved_mien(tmp_path, monkeypatch):
    _write_cfg(tmp_path, monkeypatch, work=[])
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".mien").write_text("work\n")
    result = _run(str(ws), monkeypatch)
    assert result.exit_code == 0
    assert "🟡" in result.output and "work?" in result.output
    assert "allow" in result.output


def test_statusline_shows_an_approved_mien_as_the_identity(tmp_path, monkeypatch):
    from mien.project import record_allow
    _write_cfg(tmp_path, monkeypatch, work=[])
    ws = tmp_path / "ws"
    ws.mkdir()
    decl = ws / ".mien"
    decl.write_text("work\n")
    record_allow(str(decl.resolve()), "work")
    result = _run(str(ws), monkeypatch)
    assert result.exit_code == 0
    assert "🟢" in result.output and "mien:work" in result.output


def test_statusline_is_silent_without_a_config(tmp_path, monkeypatch):
    # No config file at all — mien is not set up here, so print nothing.
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "does-not-exist.json"))
    monkeypatch.delenv("MIEN_PROFILE", raising=False)
    result = CliRunner().invoke(
        main, ["statusline"],
        input=json.dumps({"workspace": {"current_dir": "/w/acme/repo"}}),
    )
    assert result.exit_code == 0
    assert result.output.strip() == ""


def test_statusline_flags_a_stale_active_profile(tmp_path, monkeypatch):
    _write_cfg(tmp_path, monkeypatch, work=["*/acme/*"])
    result = _run("/w/acme/repo", monkeypatch, mien_profile="deleted-profile")
    assert result.exit_code == 0
    assert "🔴" in result.output and "deleted-profile" in result.output
    assert "unknown" in result.output


def test_statusline_resolves_by_git_remote_owner(tmp_path, monkeypatch):
    """Flat layout: no directory scope, but the repo's origin names its owner."""
    _write_cfg_remotes(tmp_path, monkeypatch,
                       work=["github.com/acme-*/*"], personal=["github.com/me/*"])
    result = _run("/anywhere/flat/api", monkeypatch,
                  remote="git@github.com:acme-core/api.git")
    assert result.exit_code == 0
    assert "🟢" in result.output and "mien:work" in result.output


def test_statusline_flags_wrong_identity_by_remote(tmp_path, monkeypatch):
    """personal is active, but this repo's origin belongs to work."""
    _write_cfg_remotes(tmp_path, monkeypatch,
                       work=["github.com/acme-*/*"], personal=["github.com/me/*"])
    result = _run("/anywhere/flat/api", monkeypatch, mien_profile="personal",
                  remote="https://github.com/acme-core/api.git")
    assert result.exit_code == 0
    assert "🔴" in result.output
    assert "repo is work's" in result.output and "personal" in result.output


def _write_cfg_full(tmp_path, monkeypatch, profiles):
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "config.json"))
    save_config(Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={}, secret_naming=SecretNaming(default="d", slack_token="s"),
        profiles=profiles,
    ))


def test_statusline_flags_a_wrong_git_author(tmp_path, monkeypatch):
    """The full mis-commit catch: no profile active, but the repo belongs to work
    while `git config user.email` is personal's known address."""
    from mien.config import GoogleService
    _write_cfg_full(tmp_path, monkeypatch, {
        "work": Profile(name="work", owns_remotes=["github.com/acme-*/*"],
                        google=GoogleService(
                            email="me@acme.example", oauth_client_id="c",
                            oauth_client_secret_ref=None, refresh_token_ref=None,
                            adc_ref=None, gcloud_config_name="work",
                            default_project=None, gcloud_login_required=True)),
        "personal": Profile(name="personal", google=GoogleService(
                            email="me@personal.example", oauth_client_id="c",
                            oauth_client_secret_ref=None, refresh_token_ref=None,
                            adc_ref=None, gcloud_config_name="personal",
                            default_project=None, gcloud_login_required=True)),
    })
    result = _run("/flat/api", monkeypatch,
                  remote="https://github.com/acme-core/api.git",
                  author_email="me@personal.example")
    assert result.exit_code == 0
    assert "🔴" in result.output
    assert "author:personal" in result.output and "repo is work's" in result.output


def test_statusline_is_calm_when_the_git_author_matches(tmp_path, monkeypatch):
    from mien.config import GoogleService
    _write_cfg_full(tmp_path, monkeypatch, {
        "work": Profile(name="work", owns_remotes=["github.com/acme-*/*"],
                        google=GoogleService(
                            email="me@acme.example", oauth_client_id="c",
                            oauth_client_secret_ref=None, refresh_token_ref=None,
                            adc_ref=None, gcloud_config_name="work",
                            default_project=None, gcloud_login_required=True)),
    })
    result = _run("/flat/api", monkeypatch,
                  remote="https://github.com/acme-core/api.git",
                  author_email="me@acme.example")
    assert result.exit_code == 0
    assert "🟢" in result.output and "mien:work" in result.output


def test_statusline_does_not_nag_on_an_unknown_git_author(tmp_path, monkeypatch):
    _write_cfg_remotes(tmp_path, monkeypatch, work=["github.com/acme-*/*"])
    result = _run("/flat/api", monkeypatch,
                  remote="https://github.com/acme-core/api.git",
                  author_email="someone@nowhere.example")
    assert result.exit_code == 0
    assert "🟢" in result.output and "mien:work" in result.output


def _run_guard(cwd, monkeypatch, mien_profile=None, remote=None, author_email=None,
               guard_env=None, force=False):
    if mien_profile is None:
        monkeypatch.delenv("MIEN_PROFILE", raising=False)
    else:
        monkeypatch.setenv("MIEN_PROFILE", mien_profile)
    if guard_env is None:
        monkeypatch.delenv("MIEN_GUARD", raising=False)
    else:
        monkeypatch.setenv("MIEN_GUARD", guard_env)
    monkeypatch.setattr("mien.cli._logical_cwd", lambda: cwd)
    monkeypatch.setattr("mien.cli.git_origin_remote", lambda _cwd: remote)
    monkeypatch.setattr("mien.cli.git_author_email", lambda _cwd: author_email)
    args = ["guard", "--force"] if force else ["guard"]
    return CliRunner().invoke(main, args)


def _run_prompt(cwd, monkeypatch, mien_profile=None, remote=None, author_email=None):
    if mien_profile is None:
        monkeypatch.delenv("MIEN_PROFILE", raising=False)
    else:
        monkeypatch.setenv("MIEN_PROFILE", mien_profile)
    monkeypatch.setattr("mien.cli._logical_cwd", lambda: cwd)
    monkeypatch.setattr("mien.cli.git_origin_remote", lambda _cwd: remote)
    monkeypatch.setattr("mien.cli.git_author_email", lambda _cwd: author_email)
    return CliRunner().invoke(main, ["prompt"])


def test_prompt_shows_the_segment_from_the_shell_cwd(tmp_path, monkeypatch):
    _write_cfg_remotes(tmp_path, monkeypatch, work=["github.com/acme-*/*"])
    result = _run_prompt("/flat/api", monkeypatch, mien_profile="work",
                         remote="https://github.com/acme-core/api.git")
    assert result.exit_code == 0
    assert "🟢" in result.output and "mien:work" in result.output
    # No trailing newline — it embeds into a prompt.
    assert not result.output.endswith("\n")


def test_prompt_flags_a_mismatch(tmp_path, monkeypatch):
    _write_cfg_remotes(tmp_path, monkeypatch,
                       work=["github.com/acme-*/*"], personal=["github.com/me/*"])
    result = _run_prompt("/flat/api", monkeypatch, mien_profile="personal",
                         remote="https://github.com/acme-core/api.git")
    assert result.exit_code == 0
    assert "🔴" in result.output and "repo is work's" in result.output


def test_prompt_is_silent_without_a_config(tmp_path, monkeypatch):
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "nope.json"))
    result = _run_prompt("/flat/api", monkeypatch, mien_profile="work",
                         remote="https://github.com/acme-core/api.git")
    assert result.exit_code == 0 and result.output == ""


def test_guard_blocks_a_wrong_active_identity(tmp_path, monkeypatch):
    _write_cfg_remotes(tmp_path, monkeypatch,
                       work=["github.com/acme-*/*"], personal=["github.com/me/*"])
    result = _run_guard("/flat/api", monkeypatch, mien_profile="personal",
                        remote="https://github.com/acme-core/api.git")
    assert result.exit_code == 1
    assert "refusing" in result.output and "personal" in result.output


def test_guard_blocks_a_wrong_commit_author_with_nothing_active(tmp_path, monkeypatch):
    from mien.config import GoogleService
    _write_cfg_full(tmp_path, monkeypatch, {
        "work": Profile(name="work", owns_remotes=["github.com/acme-*/*"],
                        google=GoogleService(
                            email="me@acme.example", oauth_client_id="c",
                            oauth_client_secret_ref=None, refresh_token_ref=None,
                            adc_ref=None, gcloud_config_name="work",
                            default_project=None, gcloud_login_required=True)),
        "personal": Profile(name="personal", google=GoogleService(
                            email="me@personal.example", oauth_client_id="c",
                            oauth_client_secret_ref=None, refresh_token_ref=None,
                            adc_ref=None, gcloud_config_name="personal",
                            default_project=None, gcloud_login_required=True)),
    })
    result = _run_guard("/flat/api", monkeypatch,
                        remote="https://github.com/acme-core/api.git",
                        author_email="me@personal.example")
    assert result.exit_code == 1
    assert "authored as personal" in result.output


def test_guard_allows_when_consistent(tmp_path, monkeypatch):
    _write_cfg_remotes(tmp_path, monkeypatch, work=["github.com/acme-*/*"])
    result = _run_guard("/flat/api", monkeypatch, mien_profile="work",
                        remote="https://github.com/acme-core/api.git")
    assert result.exit_code == 0
    assert result.output.strip() == ""


def test_guard_allows_on_an_unknown_owner(tmp_path, monkeypatch):
    _write_cfg_remotes(tmp_path, monkeypatch, work=["github.com/acme-*/*"])
    result = _run_guard("/flat/api", monkeypatch, mien_profile="personal",
                        remote="https://github.com/nobody/x.git")
    assert result.exit_code == 0


def test_guard_override_via_env_lets_it_through(tmp_path, monkeypatch):
    _write_cfg_remotes(tmp_path, monkeypatch,
                       work=["github.com/acme-*/*"], personal=["github.com/me/*"])
    result = _run_guard("/flat/api", monkeypatch, mien_profile="personal",
                        remote="https://github.com/acme-core/api.git", guard_env="off")
    assert result.exit_code == 0


def test_guard_force_flag_lets_it_through(tmp_path, monkeypatch):
    _write_cfg_remotes(tmp_path, monkeypatch,
                       work=["github.com/acme-*/*"], personal=["github.com/me/*"])
    result = _run_guard("/flat/api", monkeypatch, mien_profile="personal",
                        remote="https://github.com/acme-core/api.git", force=True)
    assert result.exit_code == 0


def test_guard_allows_when_mien_is_unconfigured(tmp_path, monkeypatch):
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "nope.json"))
    result = _run_guard("/flat/api", monkeypatch, mien_profile="personal",
                        remote="https://github.com/acme-core/api.git")
    assert result.exit_code == 0


def test_statusline_remote_owner_beats_a_directory_scope(tmp_path, monkeypatch):
    """When both signals resolve and disagree, the repo's remote wins."""
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "config.json"))
    save_config(Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={}, secret_naming=SecretNaming(default="d", slack_token="s"),
        profiles={
            "work": Profile(name="work", owns_remotes=["github.com/acme-*/*"]),
            "personal": Profile(name="personal", default_for=["*/flat/*"]),
        },
    ))
    result = _run("/anywhere/flat/api", monkeypatch,
                  remote="https://github.com/acme-core/api.git")
    assert result.exit_code == 0
    assert "🟢" in result.output and "mien:work" in result.output
