import shutil

import pytest

from moza.ambient import AmbientParseError, ambient_path, assert_parses, render_ambient, write_ambient
from moza.config import Profile, ProjectEnvScope


def test_render_matches_root_and_subdirs():
    profiles = {"ccp": Profile(name="ccp", project_env=[
        ProjectEnvScope(match="*/ccp/chemcopilot", env={"AWS_PROFILE": "ccp", "CCP": "$HOME/ccp/chemcopilot"}),
    ])}
    out = render_ambient(profiles)
    # matches on "$PWD/" so the directory root itself is covered, not just subdirs
    assert 'case "$PWD/" in */ccp/chemcopilot/*)' in out
    assert 'export AWS_PROFILE="ccp"' in out
    assert 'export CCP="$HOME/ccp/chemcopilot"' in out       # $HOME left for zsh


def test_render_trailing_glob_is_normalized():
    # a user who writes the old "/*"-style glob gets the same base
    profiles = {"p": Profile(name="p", project_env=[
        ProjectEnvScope(match="*/ccp/chemcopilot/*", env={"K": "v"})])}
    assert 'case "$PWD/" in */ccp/chemcopilot/*)' in render_ambient(profiles)


def test_render_escapes_only_quote_and_backslash_keeps_dollar_and_backtick():
    profiles = {"p": Profile(name="p", project_env=[
        ProjectEnvScope(match="*/x", env={"Q": 'a"b\\c', "V": "$HOME/y", "B": "x`y"})])}
    out = render_ambient(profiles)
    assert r'export Q="a\"b\\c"' in out       # " and \ escaped for string integrity
    assert 'export V="$HOME/y"' in out        # $ kept (feature)
    assert 'export B="x`y"' in out            # backtick NOT escaped — honestly eval'd


def test_render_empty_when_no_scopes():
    out = render_ambient({"p": Profile(name="p")})
    assert "# >>> moza ambient env" in out
    assert 'case "$PWD/"' not in out


def test_ambient_path_beside_config(monkeypatch, tmp_path):
    monkeypatch.setenv("MOZA_CONFIG", str(tmp_path / "cfg.json"))
    assert ambient_path() == tmp_path / "ambient.zsh"


@pytest.mark.skipif(not shutil.which("zsh"), reason="zsh required")
def test_assert_parses_rejects_broken_script():
    assert_parses('case "$PWD/" in */x/*)\n  export K="ok"\n;; esac\n')  # ok
    with pytest.raises(AmbientParseError):
        assert_parses('case "$PWD/" in */x/*)\n  export K="unterminated\n')  # broken


@pytest.mark.skipif(not shutil.which("zsh"), reason="zsh required")
def test_write_ambient_refuses_unparseable(monkeypatch, tmp_path):
    monkeypatch.setenv("MOZA_CONFIG", str(tmp_path / "cfg.json"))
    # _emit_value escapes \ and ", and a newline inside "..." is legal zsh, so
    # almost every value renders as a well-formed literal. The gate's real job is
    # the one thing left raw: an unbalanced command-substitution open ("$(") — that
    # is what `zsh -n` rejects, so write_ambient must refuse it.
    bad = Profile(name="p", project_env=[ProjectEnvScope(match="*/x", env={"K": "$("})])
    with pytest.raises(AmbientParseError):
        write_ambient({"p": bad})
    assert not ambient_path().exists()      # nothing written on failure


def test_write_ambient_creates_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MOZA_CONFIG", str(tmp_path / "cfg.json"))
    p = write_ambient({"p": Profile(name="p", project_env=[
        ProjectEnvScope(match="*/x", env={"K": "v"})])})
    assert p == ambient_path()
    assert 'export K="v"' in p.read_text()
