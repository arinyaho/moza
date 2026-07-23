import os
import shutil
import subprocess

import pytest

from mien.ambient import (
    FOOTER,
    HEADER,
    AmbientParseError,
    ambient_path,
    assert_parses,
    ensure_zshenv_sources,
    render_ambient,
    unexpandable_scope_vars,
    write_ambient,
)
from mien.config import Profile, ProjectEnvScope
from mien.resolve import match_base, resolve_profile


def test_render_matches_root_and_subdirs():
    profiles = {"work": Profile(name="work", project_env=[
        ProjectEnvScope(match="*/work/arinyaho", env={"AWS_PROFILE": "work", "WORK_ROOT": "$HOME/work/arinyaho"}),
    ])}
    out = render_ambient(profiles)
    # matches on "$PWD/" so the directory root itself is covered, not just subdirs
    assert 'case "$PWD/" in */work/arinyaho/*)' in out
    assert 'export AWS_PROFILE="work"' in out
    assert 'export WORK_ROOT="$HOME/work/arinyaho"' in out       # $HOME left for zsh


def test_render_trailing_glob_is_normalized():
    # a user who writes the old "/*"-style glob gets the same base
    profiles = {"p": Profile(name="p", project_env=[
        ProjectEnvScope(match="*/work/arinyaho/*", env={"K": "v"})])}
    assert 'case "$PWD/" in */work/arinyaho/*)' in render_ambient(profiles)


@pytest.mark.parametrize("scope", ["~/Projects/acme", "$HOME/Projects/acme"])
def test_render_leaves_tilde_and_vars_for_zsh_to_expand(scope, monkeypatch):
    # The pattern is expanded by the shell at match time, so the generated file
    # stays correct after HOME changes and carries no sync-time environment.
    monkeypatch.setenv("HOME", "/Users/nobody-in-particular")
    out = render_ambient({"p": Profile(name="p", project_env=[
        ProjectEnvScope(match=scope, env={"K": "v"})])})
    assert f'case "$PWD/" in {scope}/*)' in out
    assert "/Users/nobody-in-particular" not in out


@pytest.mark.parametrize("scope", ["$MIEN_TEST_ROOT", "${MIEN_TEST_ROOT}/acme", "~/acme"])
def test_render_is_unaffected_by_an_empty_variable_or_home(scope, monkeypatch):
    # Identity resolution refuses to expand an empty reference (it would widen the
    # scope); the generated script never expands anything at sync time, so an empty
    # value in the sync-time environment leaves its output byte-for-byte unchanged.
    out = render_ambient({"p": Profile(name="p", project_env=[
        ProjectEnvScope(match=scope, env={"K": "v"})])})
    monkeypatch.setenv("MIEN_TEST_ROOT", "")
    monkeypatch.setenv("HOME", "")
    assert render_ambient({"p": Profile(name="p", project_env=[
        ProjectEnvScope(match=scope, env={"K": "v"})])}) == out
    assert f'case "$PWD/" in {scope}/*)' in out


@pytest.mark.parametrize("scope,expected", [
    ("$WORK_ROOT/*", ["WORK_ROOT"]),                  # collapses to the pattern "/*"
    ("${WORK_ROOT}/acme", ["WORK_ROOT"]),             # braced form counts too
    ("$FOO/$BAR/x", ["FOO", "BAR"]),                  # every offender, in order
    ("$FOO/$FOO/x", ["FOO"]),                         # deduped
    ("$HOME/Projects/acme", []),                      # zsh sets HOME before .zshenv
    ("$TMPDIR/scratch", ["TMPDIR"]),                  # launchd sets it on macOS, but
                                                      # stock sshd/Linux PAM do not, and
                                                      # mien pins no platform — so warn
    ("$ZDOTDIR/work", ["ZDOTDIR"]),                   # zsh never sets it; and if the user
                                                      # did, zsh reads $ZDOTDIR/.zshenv, not
                                                      # the ~/.zshenv this code writes to
    ("$HOSTNAME/x", ["HOSTNAME"]),                    # zsh sets HOST, not HOSTNAME
    ("$HOST/x", []),                                  # ...and HOST really is set
    ("$TTY/x", ["TTY"]),                              # set but EMPTY off a tty, which
                                                      # collapses the scope just like unset
    ("$TERM/x", ["TERM"]),                            # only a terminal app sets these two;
    ("$LANG/x", ["LANG"]),                            # a launchd-started zsh has neither,
                                                      # and ~/.zshenv is read by every zsh
    ("~/Projects/acme", []),                          # tilde needs no variable
    ("/Users/nobody/Projects/acme", []),              # literal
    ("*/work/arinyaho", []),                          # plain glob
    ("${WORK_ROOT:-/tmp}/x", []),                     # not a $VAR/${VAR} form
])
def test_unexpandable_scope_vars_flags_only_late_variables(scope, expected):
    assert unexpandable_scope_vars(scope) == expected


@pytest.mark.parametrize("scope", ["$WORK_ROOT/*", "~/Projects/acme"])
def test_render_is_identical_whether_or_not_the_scope_is_flagged(scope, monkeypatch):
    # The warning is advisory: detection must not change one byte of the script.
    profiles = {"p": Profile(name="p", project_env=[
        ProjectEnvScope(match=scope, env={"AWS_PROFILE": "work"})])}
    monkeypatch.setenv("WORK_ROOT", "/Users/nobody/work")
    out = render_ambient(profiles)
    monkeypatch.delenv("WORK_ROOT")
    assert render_ambient(profiles) == out                    # no sync-time expansion
    assert out == (
        f'{HEADER}\ncase "$PWD/" in {match_base(scope)}/*)\n'
        f'  export AWS_PROFILE="work"\n;; esac\n{FOOTER}\n'
    )


def test_render_escapes_only_quote_and_backslash_keeps_dollar_and_backtick():
    profiles = {"p": Profile(name="p", project_env=[
        ProjectEnvScope(match="*/x", env={"Q": 'a"b\\c', "V": "$HOME/y", "B": "x`y"})])}
    out = render_ambient(profiles)
    assert r'export Q="a\"b\\c"' in out       # " and \ escaped for string integrity
    assert 'export V="$HOME/y"' in out        # $ kept (feature)
    assert 'export B="x`y"' in out            # backtick NOT escaped — honestly eval'd


def test_render_empty_when_no_scopes():
    out = render_ambient({"p": Profile(name="p")})
    assert "# >>> mien ambient env" in out
    assert 'case "$PWD/"' not in out


def test_ambient_path_beside_config(monkeypatch, tmp_path):
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "cfg.json"))
    assert ambient_path() == tmp_path / "ambient.zsh"


@pytest.mark.skipif(not shutil.which("zsh"), reason="zsh required")
def test_assert_parses_rejects_broken_script():
    assert_parses('case "$PWD/" in */x/*)\n  export K="ok"\n;; esac\n')  # ok
    with pytest.raises(AmbientParseError):
        assert_parses('case "$PWD/" in */x/*)\n  export K="unterminated\n')  # broken


@pytest.mark.skipif(not shutil.which("zsh"), reason="zsh required")
def test_write_ambient_refuses_unparseable(monkeypatch, tmp_path):
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "cfg.json"))
    # _emit_value escapes \ and ", and a newline inside "..." is legal zsh, so
    # almost every value renders as a well-formed literal. The gate's real job is
    # the one thing left raw: an unbalanced command-substitution open ("$(") — that
    # is what `zsh -n` rejects, so write_ambient must refuse it.
    bad = Profile(name="p", project_env=[ProjectEnvScope(match="*/x", env={"K": "$("})])
    with pytest.raises(AmbientParseError):
        write_ambient({"p": bad})
    assert not ambient_path().exists()      # nothing written on failure


def test_write_ambient_creates_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "cfg.json"))
    p = write_ambient({"p": Profile(name="p", project_env=[
        ProjectEnvScope(match="*/x", env={"K": "v"})])})
    assert p == ambient_path()
    assert 'export K="v"' in p.read_text()


def test_ensure_zshenv_inserts_then_idempotent(tmp_path):
    zshenv = tmp_path / ".zshenv"
    zshenv.write_text("# user content\nexport FOO=1\n")
    ambient = tmp_path / "ambient.zsh"
    assert ensure_zshenv_sources(zshenv, ambient) is True
    body = zshenv.read_text()
    assert "# user content" in body and str(ambient) in body
    assert body.count("mien ambient (zshenv)") == 2
    assert ensure_zshenv_sources(zshenv, ambient) is False       # re-run: no change
    assert zshenv.read_text().count("mien ambient (zshenv)") == 2


@pytest.mark.skipif(not shutil.which("zsh"), reason="zsh required")
def test_behavioral_ambient_applies_under_matching_pwd(monkeypatch, tmp_path):
    # End-to-end: a real zsh, cd'd into a matching dir, sourcing ambient.zsh,
    # actually exports the value. This is the only test that proves it WORKS.
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "cfg.json"))
    matchdir = tmp_path / "proj" / "work" / "arinyaho"
    matchdir.mkdir(parents=True)
    write_ambient({"p": Profile(name="p", project_env=[
        ProjectEnvScope(match="*/work/arinyaho", env={"AWS_PROFILE": "work"})])})
    amb = ambient_path()
    script = f'cd "{matchdir}"; source "{amb}"; print -r -- "$AWS_PROFILE"'
    out = subprocess.run(["zsh", "-fc", script], text=True, capture_output=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "work"        # value applied at the directory root


@pytest.mark.skipif(not shutil.which("zsh"), reason="zsh required")
def test_behavioral_zshenv_sources_ambient(monkeypatch, tmp_path):
    # Prove the FULL wiring: a zshenv with the managed region, when sourced by a
    # real zsh under a matching $PWD, pulls in ambient.zsh and applies the value.
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "cfg.json"))
    matchdir = tmp_path / "proj" / "work" / "arinyaho"
    matchdir.mkdir(parents=True)
    write_ambient({"p": Profile(name="p", project_env=[
        ProjectEnvScope(match="*/work/arinyaho", env={"AWS_PROFILE": "work"})])})
    zshenv = tmp_path / ".zshenv"
    ensure_zshenv_sources(zshenv, ambient_path())
    script = f'cd "{matchdir}"; source "{zshenv}"; print -r -- "$AWS_PROFILE"'
    out = subprocess.run(["zsh", "-fc", script], text=True, capture_output=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "work"      # value applied via zshenv -> ambient.zsh


@pytest.mark.skipif(not shutil.which("zsh"), reason="zsh required")
def test_behavioral_tilde_scope_agrees_with_identity_resolution(monkeypatch, tmp_path):
    # The claim both sides are documented to keep: one scope string, one directory,
    # the same answer from the generated zsh and from resolve_profile.
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "cfg.json"))
    home = tmp_path / "home"
    matchdir = home / "Projects" / "acme"
    matchdir.mkdir(parents=True)
    write_ambient({"p": Profile(name="p", project_env=[
        ProjectEnvScope(match="~/Projects/acme", env={"AWS_PROFILE": "work"})])})
    script = f'cd "{matchdir}"; source "{ambient_path()}"; print -r -- "$AWS_PROFILE"'
    out = subprocess.run(["zsh", "-fc", script], text=True, capture_output=True,
                         env={**os.environ, "HOME": str(home)})
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "work"                  # zsh: the scope covers it

    monkeypatch.setenv("HOME", str(home))
    identity = {"p": Profile(name="p", default_for=["~/Projects/acme"])}
    assert resolve_profile(identity, str(matchdir)) == "p"   # identity: likewise


def test_write_ambient_leaves_no_tmp_files(monkeypatch, tmp_path):
    monkeypatch.setenv("MIEN_CONFIG", str(tmp_path / "cfg.json"))
    write_ambient({"p": Profile(name="p", project_env=[
        ProjectEnvScope(match="*/x", env={"K": "v"})])})
    leftovers = [f for f in ambient_path().parent.iterdir() if f.name.endswith(".tmp")]
    assert leftovers == []                       # atomic write cleans up its temp


def test_ensure_zshenv_failed_write_preserves_original(monkeypatch, tmp_path):
    from mien import ambient as _amb
    zshenv = tmp_path / ".zshenv"
    zshenv.write_text("# precious user content\nexport FOO=1\n")
    ambient = tmp_path / "ambient.zsh"
    # simulate an interrupted rename: original must survive, no partial, no temp left
    monkeypatch.setattr(_amb.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError):
        _amb.ensure_zshenv_sources(zshenv, ambient)
    assert zshenv.read_text() == "# precious user content\nexport FOO=1\n"   # untouched
    leftovers = [f for f in tmp_path.iterdir() if f.name.endswith(".tmp")]
    assert leftovers == []                       # temp cleaned up on failure
