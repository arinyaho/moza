"""Resolve a profile from the working directory.

A profile may claim directories via `default_for` globs. Resolution is a pure
function of the config and a path — it reads no environment and caches nothing,
so it returns the same answer in a long-lived interactive shell and in an agent
harness that starts a fresh shell for every command.
"""

from __future__ import annotations

import fnmatch

from moza.config import Profile


class AmbiguousScope(Exception):
    """Two or more profiles claim a directory with equal specificity."""


def match_base(match: str) -> str:
    """Normalize a scope glob to its directory root.

    Strips a trailing '/*' or '/' so that a scope covers the directory itself and
    everything beneath it. Mirrors the `case "$PWD/" in <base>/*)` form emitted by
    `moza env sync`, so ambient env and identity agree on what a scope covers.
    """
    base = match
    if base.endswith("/*"):
        base = base[:-2]
    return base.rstrip("/")


def _covers(base: str, path: str) -> bool:
    """True if `base` covers `path` — the directory itself or a descendant.

    `fnmatch`'s '*' spans '/', matching the shell `case` patterns these globs are
    also compiled into. Descendants are tested against '<base>/*' rather than by
    string prefix, so '*/Projects/acme' does not capture '.../acme-fork'.
    """
    return fnmatch.fnmatch(path, base) or fnmatch.fnmatch(path, f"{base}/*")


def _specificity(base: str) -> int:
    """Longer globs are treated as more specific, so a scope nested inside another
    wins. This is a lexical rule, not a semantic one: it cannot tell that
    '*/Projects/acme' is narrower than a longer but broader literal path. Equal
    scores are refused rather than broken arbitrarily, which keeps the rule honest
    about what it does not know."""
    return len(base)


def resolve_profile(profiles: dict[str, Profile], path: str) -> str | None:
    """Return the profile claiming `path`, or None if no scope covers it.

    Raises AmbiguousScope when two profiles claim it with equal specificity;
    guessing between them would misroute credentials silently.
    """
    best: dict[str, int] = {}
    for name in sorted(profiles):
        for raw in profiles[name].default_for:
            base = match_base(raw)
            if _covers(base, path):
                score = _specificity(base)
                if score > best.get(name, -1):
                    best[name] = score

    if not best:
        return None

    top = max(best.values())
    winners = sorted(n for n, s in best.items() if s == top)
    if len(winners) > 1:
        raise AmbiguousScope(
            f"{path} is claimed with equal specificity by: {', '.join(winners)}. "
            "Narrow one of their default_for scopes, or name a profile explicitly."
        )
    return winners[0]
