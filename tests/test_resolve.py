import pytest

from moza.config import Profile
from moza.resolve import AmbiguousScope, expand_scope, match_base, resolve_profile


def prof(name: str, *globs: str) -> Profile:
    return Profile(name=name, default_for=list(globs))


def profiles(*ps: Profile) -> dict[str, Profile]:
    return {p.name: p for p in ps}


class TestMatchBase:
    """Where a scope ends must agree with the zsh `case "$PWD/" in base/*)` form
    that `moza env sync` generates, or ambient env and identity would disagree
    about which directories a scope covers. This half is normalization only: the
    generated script keeps the scope as written and lets zsh expand it, so the
    matching side gets that expansion from `expand_scope` instead."""

    @pytest.mark.parametrize("raw,expected", [
        ("*/Projects/moza", "*/Projects/moza"),
        ("*/Projects/moza/", "*/Projects/moza"),
        ("*/Projects/moza/*", "*/Projects/moza"),
        ("/", ""),
    ])
    def test_strips_trailing_slash_and_star(self, raw, expected):
        assert match_base(raw) == expected

    @pytest.mark.parametrize("raw", ["~/Projects/moza", "$HOME/Projects/moza"])
    def test_does_not_expand_so_env_sync_output_is_unchanged(self, raw, monkeypatch):
        """`moza env sync` emits this text straight into a zsh `case` pattern, where
        the shell expands it at match time. Expanding here would bake the sync-time
        HOME into a file every shell sources."""
        monkeypatch.setenv("HOME", "/Users/me")
        assert match_base(raw + "/*") == raw
        assert match_base(raw) == raw


class TestExpandScope:
    """zsh expands `~` and `$VAR` in a `case` pattern before matching; `fnmatch`
    expands neither. Without an equivalent step the identical scope string would
    cover a directory for ambient env and not for identity."""

    def test_expands_tilde_and_variables(self, monkeypatch):
        monkeypatch.setenv("HOME", "/Users/me")
        monkeypatch.setenv("MOZA_TEST_ROOT", "/srv/clients")
        assert expand_scope("~/Projects/acme") == "/Users/me/Projects/acme"
        assert expand_scope("$HOME/Projects/acme") == "/Users/me/Projects/acme"
        assert expand_scope("$MOZA_TEST_ROOT/acme") == "/srv/clients/acme"

    def test_leaves_ordinary_globs_alone(self, monkeypatch):
        monkeypatch.setenv("HOME", "/Users/me")
        assert expand_scope("*/Projects/acme") == "*/Projects/acme"

    def test_leaves_an_undefined_variable_literal(self, monkeypatch):
        """zsh would expand it away and leave the far broader '/Projects/acme'.
        Silently widening a scope is how credentials get misrouted, so an unset
        variable stays literal and matches nothing."""
        monkeypatch.delenv("MOZA_NO_SUCH_VAR", raising=False)
        assert expand_scope("$MOZA_NO_SUCH_VAR/Projects/acme") == (
            "$MOZA_NO_SUCH_VAR/Projects/acme"
        )


class TestResolveExpandedScopes:
    def test_tilde_scope_covers_the_home_directory(self, monkeypatch):
        monkeypatch.setenv("HOME", "/Users/me")
        p = profiles(prof("work", "~/Projects/acme"))
        assert resolve_profile(p, "/Users/me/Projects/acme") == "work"
        assert resolve_profile(p, "/Users/me/Projects/acme/src") == "work"
        # expanded to THIS home — '~' is not a wildcard standing for any home
        assert resolve_profile(p, "/Users/other/Projects/acme") is None
        # and it is not the literal text '~/...' that got matched
        assert resolve_profile(p, "~/Projects/acme") is None

    def test_home_variable_scope_covers_the_home_directory(self, monkeypatch):
        monkeypatch.setenv("HOME", "/Users/me")
        p = profiles(prof("work", "$HOME/Projects/acme"))
        assert resolve_profile(p, "/Users/me/Projects/acme/src") == "work"
        assert resolve_profile(p, "/Users/other/Projects/acme") is None

    def test_arbitrary_variable_scope(self, monkeypatch):
        monkeypatch.setenv("MOZA_TEST_ROOT", "/srv/clients")
        p = profiles(prof("work", "$MOZA_TEST_ROOT/acme"))
        assert resolve_profile(p, "/srv/clients/acme/src") == "work"
        assert resolve_profile(p, "/srv/clients/acme-fork") is None

    @pytest.mark.parametrize("raw", [
        "~/Projects/acme", "~/Projects/acme/", "~/Projects/acme/*",
    ])
    def test_trailing_forms_are_normalized_after_expansion(self, raw, monkeypatch):
        monkeypatch.setenv("HOME", "/Users/me")
        p = profiles(prof("work", raw))
        assert resolve_profile(p, "/Users/me/Projects/acme") == "work"
        assert resolve_profile(p, "/Users/me/Projects/acme/deep") == "work"
        assert resolve_profile(p, "/Users/me/Projects/acme-fork") is None

    def test_undefined_variable_does_not_widen_the_scope(self, monkeypatch):
        monkeypatch.delenv("MOZA_NO_SUCH_VAR", raising=False)
        p = profiles(prof("work", "$MOZA_NO_SUCH_VAR/Projects/acme"))
        assert resolve_profile(p, "/Projects/acme") is None
        assert resolve_profile(p, "/Users/me/Projects/acme") is None

    def test_specificity_is_scored_on_the_expanded_scope(self, monkeypatch):
        """Unexpanded, the shorter '~/Projects/acme' would lose to the longer but
        broader literal parent; expanded, the nested scope is longer and wins."""
        monkeypatch.setenv("HOME", "/Users/me")
        p = profiles(
            prof("personal", "/Users/me/Projects"),
            prof("work", "~/Projects/acme"),
        )
        assert resolve_profile(p, "/Users/me/Projects/acme/src") == "work"
        assert resolve_profile(p, "/Users/me/Projects/other") == "personal"

    def test_two_spellings_of_one_directory_are_ambiguous(self, monkeypatch):
        """'~/Projects/shared' and '$HOME/Projects/shared' name the same directory,
        so two profiles spelling it differently is the same clash as spelling it
        identically — not a silent miss."""
        monkeypatch.setenv("HOME", "/Users/me")
        p = profiles(
            prof("a", "~/Projects/shared"),
            prof("b", "$HOME/Projects/shared"),
        )
        with pytest.raises(AmbiguousScope) as exc:
            resolve_profile(p, "/Users/me/Projects/shared")
        assert "a" in str(exc.value) and "b" in str(exc.value)


class TestResolveProfile:
    def test_no_scopes_resolves_to_nothing(self):
        assert resolve_profile(profiles(prof("work")), "/Users/me/Projects/x") is None

    def test_matches_the_directory_itself(self):
        p = profiles(prof("work", "*/Projects/acme"))
        assert resolve_profile(p, "/Users/me/Projects/acme") == "work"

    def test_matches_a_descendant(self):
        p = profiles(prof("work", "*/Projects/acme"))
        assert resolve_profile(p, "/Users/me/Projects/acme/deep/nested") == "work"

    def test_does_not_match_a_sibling_with_a_shared_prefix(self):
        """`acme` must not capture `acme-fork` — a prefix match without the
        separator would route a different project's commits to the wrong account."""
        p = profiles(prof("work", "*/Projects/acme"))
        assert resolve_profile(p, "/Users/me/Projects/acme-fork") is None

    def test_unrelated_directory_resolves_to_nothing(self):
        p = profiles(prof("work", "*/Projects/acme"))
        assert resolve_profile(p, "/tmp/scratch") is None

    def test_longest_glob_wins(self):
        p = profiles(
            prof("personal", "*/Projects"),
            prof("work", "*/Projects/acme"),
        )
        assert resolve_profile(p, "/Users/me/Projects/acme/src") == "work"
        assert resolve_profile(p, "/Users/me/Projects/other") == "personal"

    def test_equally_specific_scopes_raise(self):
        """Two scopes of identical specificity have no principled winner. Picking
        one silently would misroute credentials, so refuse and make the user say."""
        p = profiles(
            prof("a", "*/Projects/shared"),
            prof("b", "*/Projects/shared"),
        )
        with pytest.raises(AmbiguousScope) as exc:
            resolve_profile(p, "/Users/me/Projects/shared")
        assert "a" in str(exc.value) and "b" in str(exc.value)

    def test_a_profile_may_claim_several_scopes(self):
        p = profiles(prof("work", "*/Projects/acme", "*/work/*"))
        assert resolve_profile(p, "/Users/me/work/thing") == "work"
        assert resolve_profile(p, "/Users/me/Projects/acme") == "work"

    def test_same_profile_matching_twice_is_not_ambiguous(self):
        """Overlapping scopes on one profile agree on the answer, so there is
        nothing to disambiguate."""
        p = profiles(prof("work", "*/Projects", "*/Projects/acme"))
        assert resolve_profile(p, "/Users/me/Projects/acme") == "work"
