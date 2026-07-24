"""Project-local identity declaration: a `.mien` file naming the profile a
workspace acts as, honoured only after the user approves it.

The declaration lives with the work (a `.mien` in the workspace) rather than as a
glob in the central config, so binding a workspace to an identity is one line
where you already are. But a `.mien` is a checked-out file, and the rule that a
clone must not choose which identity acts still holds — so a declaration drives
*acting* identity only after `mien allow` records the user's approval of that
exact (path, profile) in their own state. A cloned repository's `.mien` is inert
until approved, and a changed declaration must be re-approved. This mirrors
direnv's `allow`, applied to identity instead of environment.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from mien.config import config_path

DECL_FILENAME = ".mien"


def _read_declaration(path: Path) -> str | None:
    """The profile a `.mien` file names — its first non-empty, non-comment line's
    first token — or None if unreadable/empty."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped.split()[0]
    return None


def find_declaration(start: str) -> tuple[str | None, str | None]:
    """The nearest `.mien` declaration walking up from ``start``.

    Returns ``(profile, declaration_path)`` for the closest `.mien` at or above
    ``start``, or ``(None, None)``. The absolute declaration path is what `allow`
    is keyed on, so two workspaces that both declare the same profile are approved
    independently.
    """
    here = Path(start)
    for directory in (here, *here.parents):
        candidate = directory / DECL_FILENAME
        if candidate.is_file():
            profile = _read_declaration(candidate)
            if profile:
                return profile, str(candidate.resolve())
    return None, None


def _allowed_path() -> Path:
    """User state for approvals — beside the config, never in a repo."""
    return config_path().parent / "allowed.json"


def _load_allowed() -> dict[str, str]:
    try:
        data = json.loads(_allowed_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def allowed_declarations() -> dict[str, str]:
    """Every approved declaration as ``{declaration_path: profile}`` — the source
    of the workspace directories `git sync` turns into `gitdir` includes."""
    return _load_allowed()


def is_allowed(declaration_path: str, profile: str) -> bool:
    """True only if the user has approved *this* declaration path for *this*
    profile. A different profile at the same path (the file was edited) is not
    approved until `allow` runs again — the re-confirmation on change."""
    return _load_allowed().get(declaration_path) == profile


def record_allow(declaration_path: str, profile: str) -> None:
    allowed = _load_allowed()
    allowed[declaration_path] = profile
    path = _allowed_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, json.dumps(allowed, indent=2).encode("utf-8"))
    finally:
        os.close(fd)


def _global_gitignore() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "git" / "ignore"


def ensure_gitignored() -> bool:
    """Add `.mien` to the user's *global* git ignore so it is never committed —
    it is a private, local marker (it names your own profile). Touches no
    repository. Returns True if it added the entry, False if already present."""
    ignore = _global_gitignore()
    try:
        existing = ignore.read_text(encoding="utf-8").splitlines() if ignore.exists() else []
        if DECL_FILENAME in (line.strip() for line in existing):
            return False
        ignore.parent.mkdir(parents=True, exist_ok=True)
        with ignore.open("a", encoding="utf-8") as fh:
            if existing and not existing[-1].endswith("\n"):
                fh.write("\n")
            fh.write(DECL_FILENAME + "\n")
        return True
    except OSError:
        return False


def write_declaration(directory: str, profile: str) -> str:
    """Write a `.mien` naming ``profile`` in ``directory``; return its path."""
    path = Path(directory) / DECL_FILENAME
    path.write_text(profile + "\n", encoding="utf-8")
    return str(path.resolve())
