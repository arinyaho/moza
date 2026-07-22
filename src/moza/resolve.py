"""Resolve a profile from the working directory.

A profile may claim directories via `default_for` globs. Resolution is a function
of the config and the path it is handed — it inspects no working directory of its
own and caches nothing, so it returns the same answer in a long-lived interactive
shell and in an agent harness that starts a fresh shell for every command.

The one thing it does read from the environment is what the shell would read from
it anyway: `~` and `$VAR` inside a scope, expanded by `expand_scope` at the point
where zsh expands them in the `case` pattern `moza env sync` generates.
"""

from __future__ import annotations

import fnmatch
import os

from moza.config import Profile


class AmbiguousScope(Exception):
    """Two or more profiles claim a directory with equal specificity."""


def match_base(match: str) -> str:
    """Normalize a scope glob to its directory root.

    Strips a trailing '/*' or '/' so that a scope covers the directory itself and
    everything beneath it. Mirrors the `case "$PWD/" in <base>/*)` form emitted by
    `moza env sync`, so ambient env and identity agree on where a scope ends.

    Normalization only — deliberately no expansion. `moza env sync` writes the
    scope into the generated script as written and lets zsh expand `~` and `$VAR`
    when the `case` runs, which keeps the script valid after HOME changes and keeps
    the sync-time environment out of a file that is read in every shell. Identity
    resolution gets the same expansion by calling `expand_scope` itself; see
    `resolve_profile`.
    """
    base = match
    if base.endswith("/*"):
        base = base[:-2]
    return base.rstrip("/")


def expand_scope(match: str) -> str:
    """Expand `~` and `$VAR` in a scope, the way the shell expands the same text.

    zsh performs tilde and parameter expansion on a `case` pattern before matching,
    so `case "$PWD/" in ~/Projects/acme/*)` fires inside the home directory.
    `fnmatch` performs neither, so without this the identical scope string would
    cover a directory for ambient env and not for identity — a hard "no profile
    claims ..." at best, and the wrong identity if some broader scope catches it.

    An undefined variable is left as written rather than expanded away: zsh would
    turn '$UNSET/Projects' into the far broader '/Projects', and silently widening
    a scope is how credentials get misrouted. Left literal, it simply matches
    nothing.
    """
    return os.path.expandvars(os.path.expanduser(match))


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

    `path` is supplied by the caller rather than read here, so the answer depends
    only on the arguments. Scopes are expanded (`expand_scope`) and then normalized
    (`match_base`) so that a scope means the same directory tree here as it does in
    the zsh `case` that `moza env sync` generates from it.

    Raises AmbiguousScope when two profiles claim it with equal specificity;
    guessing between them would misroute credentials silently.
    """
    best: dict[str, int] = {}
    for name in sorted(profiles):
        for raw in profiles[name].default_for:
            base = match_base(expand_scope(raw))
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
