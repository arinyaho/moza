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
    def test_emits_both_url_shapes_verified_against_real_git(self):
        # These exact strings were verified to make `git config user.email`
        # resolve for https://, ssh://, and scp (git@host:owner) origins, and to
        # NOT resolve for a different owner.
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
    assert gitdir_pattern("/home/me/ccp") == "gitdir:/home/me/ccp/**"


def test_render_profile_gitconfig():
    out = render_profile_gitconfig("me@x.example", "Me")
    assert "[user]" in out and "email = me@x.example" in out and "name = Me" in out
    assert "Managed by mien" in out


def test_render_main_gitconfig():
    out = render_main_gitconfig([
        ("hasconfig:remote.*.url:**/*github.com/acme/**", "/c/git/work.gitconfig"),
        ("gitdir:/home/me/ccp/**", "/c/git/work.gitconfig"),
    ])
    assert '[includeIf "hasconfig:remote.*.url:**/*github.com/acme/**"]' in out
    assert '[includeIf "gitdir:/home/me/ccp/**"]' in out
    assert "path = /c/git/work.gitconfig" in out
