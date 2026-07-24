import json

from click.testing import CliRunner

from mien.cli import main
from mien.config import (BackendConfig, Config, Profile, SecretNaming,
                         save_config)
from mien.statusline import render_segment


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
        assert "✗" in out

    def test_ambiguous_dir_without_env_is_alarm(self):
        out = render_segment(None, None, ambiguous=True)
        assert "🔴" in out and "ambiguous" in out

    def test_ambiguous_dir_is_calm_when_env_breaks_the_tie(self):
        # An explicit profile resolves the ambiguity, exactly as `mien run` does.
        out = render_segment("work", None, ambiguous=True)
        assert "🟢" in out and "mien:work" in out

    def test_stale_unknown_env_profile_is_alarm(self):
        out = render_segment("ghost", None, env_unknown=True)
        assert "🔴" in out and "ghost" in out and "unknown" in out

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


def _run(cwd, monkeypatch, mien_profile=None):
    if mien_profile is None:
        monkeypatch.delenv("MIEN_PROFILE", raising=False)
    else:
        monkeypatch.setenv("MIEN_PROFILE", mien_profile)
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
