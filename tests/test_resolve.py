import pytest

from moza.config import Profile
from moza.resolve import AmbiguousScope, match_base, resolve_profile


def prof(name: str, *globs: str) -> Profile:
    return Profile(name=name, default_for=list(globs))


def profiles(*ps: Profile) -> dict[str, Profile]:
    return {p.name: p for p in ps}


class TestMatchBase:
    """Normalization must agree with the zsh `case "$PWD/" in base/*)` form that
    `moza env sync` generates, or ambient env and identity would disagree about
    which directories a scope covers."""

    @pytest.mark.parametrize("raw,expected", [
        ("*/Projects/moza", "*/Projects/moza"),
        ("*/Projects/moza/", "*/Projects/moza"),
        ("*/Projects/moza/*", "*/Projects/moza"),
        ("/", ""),
    ])
    def test_strips_trailing_slash_and_star(self, raw, expected):
        assert match_base(raw) == expected


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
