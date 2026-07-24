import os
import shutil
import subprocess

import pytest

from mien.config import AtlassianService, GitHubService, GoogleService, Profile
from mien.gitsync import (default_git_email, default_git_name, git_identity,
                          gitdir_pattern, hasconfig_patterns,
                          render_main_gitconfig, render_profile_gitconfig)


def _prof(name, **kw):
    g = GoogleService(email=kw.get("google"), oauth_client_id="c",
                      oauth_client_secret_ref=None, refresh_token_ref=None,
                      adc_ref=None, gcloud_config_name=name, default_project=None,
                      gcloud_login_required=True) if kw.get("google") else None
    a = AtlassianService(email=kw["atlassian"], api_token_ref="r",
                         base_url="https://x.atlassian.net") if kw.get("atlassian") else None
    h = GitHubService(username=kw["github"], host="github.com", token_ref="r") \
        if kw.get("github") else None
    return Profile(name=name, google=g, atlassian=a, github=h,
                   git_email=kw.get("git_email"), git_name=kw.get("git_name"))


class TestHasconfigPatterns:
    def test_emits_both_url_shapes(self):
        # Exact strings pinned here; that they actually make `git config
        # user.email` resolve for https/ssh/scp (and not for another owner) is
        # verified by test_generated_includeif_resolves_the_author_in_real_git.
        pats = hasconfig_patterns("github.com/acme-inc/*")
        assert pats == [
            "hasconfig:remote.*.url:**/*github.com/acme-inc/**",
            "hasconfig:remote.*.url:**github.com:acme-inc/**",
        ]

    def test_tolerates_no_trailing_glob(self):
        assert hasconfig_patterns("github.com/acme") == [
            "hasconfig:remote.*.url:**/*github.com/acme/**",
            "hasconfig:remote.*.url:**github.com:acme/**",
        ]

    def test_empty_for_a_hostless_value(self):
        assert hasconfig_patterns("acme") == []


class TestGitIdentity:
    def test_explicit_fields_win(self):
        p = _prof("work", google="g@x.example", github="ghuser",
                  git_email="me@work.example", git_name="Work Me")
        assert git_identity(p) == ("me@work.example", "Work Me")

    def test_falls_back_to_google_email_and_github_name(self):
        p = _prof("work", google="g@x.example", github="ghuser")
        assert git_identity(p) == ("g@x.example", "ghuser")

    def test_falls_back_to_atlassian_then_email_localpart(self):
        p = _prof("work", atlassian="a@client.example")
        assert git_identity(p) == ("a@client.example", "a")

    def test_none_when_no_email_anywhere(self):
        assert git_identity(_prof("work", github="ghuser")) is None

    def test_defaults(self):
        p = _prof("work", google="g@x.example", github="ghuser")
        assert default_git_email(p) == "g@x.example"
        assert default_git_name(p) == "ghuser"


def test_gitdir_pattern():
    assert gitdir_pattern("/home/me/proj") == "gitdir:/home/me/proj/**"


def test_render_profile_gitconfig():
    out = render_profile_gitconfig("me@x.example", "Me")
    assert "[user]" in out and "email = me@x.example" in out and "name = Me" in out
    assert "Managed by mien" in out


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_generated_includeif_resolves_the_author_in_real_git(tmp_path):
    """The hasconfig patterns are finicky (a leading `**` can't cross a URL
    scheme's `//`), so back the exact strings with git's own resolution: a repo
    whose origin is owned resolves to the profile's email, one that isn't stays
    empty — across https, ssh, and scp forms."""
    home = tmp_path / "home"
    home.mkdir()
    pgc = tmp_path / "work.gitconfig"
    pgc.write_text(render_profile_gitconfig("me@acme.example", "acme-me"))
    blocks = [(c, str(pgc)) for c in hasconfig_patterns("github.com/acme-inc/*")]
    main = tmp_path / "mien-gitconfig"
    main.write_text(render_main_gitconfig(blocks))
    (home / ".gitconfig").write_text(f"[include]\n\tpath = {main}\n")

    env = {**os.environ, "HOME": str(home), "XDG_CONFIG_HOME": str(tmp_path / "xdg"),
           "GIT_CONFIG_NOSYSTEM": "1"}
    repo = home / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], env=env, check=True)

    def email_for(url: str) -> str:
        subprocess.run(["git", "-C", str(repo), "remote", "remove", "origin"],
                       env=env, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", url],
                       env=env, check=True)
        return subprocess.run(["git", "-C", str(repo), "config", "user.email"],
                              env=env, capture_output=True, text=True).stdout.strip()

    assert email_for("https://github.com/acme-inc/foo.git") == "me@acme.example"
    assert email_for("ssh://git@github.com/acme-inc/baz.git") == "me@acme.example"
    assert email_for("git@github.com:acme-inc/bar.git") == "me@acme.example"
    assert email_for("https://github.com/other/x.git") == ""  # not an owned repo


def test_render_main_gitconfig():
    out = render_main_gitconfig([
        ("hasconfig:remote.*.url:**/*github.com/acme/**", "/c/git/work.gitconfig"),
        ("gitdir:/home/me/proj/**", "/c/git/work.gitconfig"),
    ])
    assert '[includeIf "hasconfig:remote.*.url:**/*github.com/acme/**"]' in out
    assert '[includeIf "gitdir:/home/me/proj/**"]' in out
    assert "path = /c/git/work.gitconfig" in out
