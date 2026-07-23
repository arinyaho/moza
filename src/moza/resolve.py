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
import glob
import os
import re

from moza.config import Profile

# `$VAR` / `${VAR}`, with the same name characters `os.path.expandvars` accepts.
# The braced form is tried first so `${VAR}` is not read as `$VAR` plus braces.
# Anything else that starts with `$` (a bare `$`, `${VAR:-x}`, `$1`) matches
# nothing here and is left exactly as written.
_VAR_RE = re.compile(r"\$\{([A-Za-z0-9_]+)\}|\$([A-Za-z0-9_]+)")


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


def _expand_vars(match: str) -> str:
    """Substitute `$VAR` / `${VAR}` from the environment, except where the value
    would be empty. `os.path.expandvars` cannot express that exception: it skips
    an unset name but expands a set-but-empty one away, which is the same
    widening by a different route (`WORK_ROOT=` in a dotfile, or
    `WORK_ROOT="$SOMETHING_UNSET"` in a wrapper).

    A glob metacharacter (`*`, `?`, `[`) that arrives *in a value* is escaped, so
    `fnmatch` treats it literally. zsh does not set GLOB_SUBST by default, so a
    value like `*` from `$STARVAR` is a literal `*` in the `case` pattern `moza
    env sync` generates — it matches a directory named `*`, i.e. nothing real.
    Left unescaped, `fnmatch` would honour it as a wildcard and match a live tree
    for identity resolution while the ambient block matched nothing — silently
    widening a scope, which is how credentials get misrouted. Glob characters the
    user writes *literally in the scope* are not touched; only ones that come in
    through a variable's value are escaped, which is exactly zsh's split."""

    def sub(m: re.Match[str]) -> str:
        value = os.environ.get(m.group(1) or m.group(2))
        return glob.escape(value) if value else m.group(0)

    return _VAR_RE.sub(sub, match)


def _expand_user(match: str) -> str:
    """Expand a leading `~`, except where HOME is set but empty — `os.path
    .expanduser` has the same hole as `expandvars` there, turning '~/Projects'
    into '/Projects'. An absent HOME is not the same case: expanduser falls back
    to the password database and gets a real home."""
    if (match == "~" or match.startswith("~/")) and os.environ.get("HOME") == "":
        return match
    return os.path.expanduser(match)


def expand_scope(match: str) -> str:
    """Expand `~` and `$VAR` in a scope, the way the shell expands the same text.

    zsh performs tilde and parameter expansion on a `case` pattern before matching,
    so `case "$PWD/" in ~/Projects/acme/*)` fires inside the home directory.
    `fnmatch` performs neither, so without this the identical scope string would
    cover a directory for ambient env and not for identity — a hard "no profile
    claims ..." at best, and the wrong identity if some broader scope catches it.

    A variable that is unset OR set to the empty string is left as written rather
    than expanded away, and so is `~` under an empty HOME. This is a deliberate
    divergence from zsh, which expands both to nothing: '$EMPTY/Projects' would
    become the far broader '/Projects', and a scope that is nothing but
    '$EMPTY' would normalize to '' and cover every absolute path. Silently
    widening a scope is how credentials get misrouted. Left literal, the
    reference simply matches nothing.

    Only `$VAR` and `${VAR}` are recognized; any other `$`-form is left untouched
    rather than rejected.

    A glob character (`*`, `?`, `[`) coming from a variable's *value* is treated
    literally, not as a wildcard, matching zsh's default (no GLOB_SUBST): the
    substitution is expansion, not pattern injection. Glob characters written
    literally in the scope itself keep their wildcard meaning. See `_expand_vars`.
    """
    return _expand_vars(_expand_user(match))


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
