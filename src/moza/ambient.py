from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from moza.config import Profile, config_path
from moza.resolve import _VAR_RE, match_base

HEADER = "# >>> moza ambient env (generated — do not edit; run `moza env sync`) >>>"
FOOTER = "# <<< moza ambient env <<<"

ZSHENV_BEGIN = "# >>> moza ambient (zshenv) >>>"
ZSHENV_END = "# <<< moza ambient (zshenv) <<<"

# Parameters that already hold a NON-EMPTY value at the moment `~/.zshenv` is
# read, so a scope referring to one expands as written.
#
# The rule: a reference is "expandable" only if zsh itself sets the parameter
# before it reads any startup file, or the process that starts zsh (login(1),
# launchd, sshd, PAM, a terminal app, a parent shell) puts it in the environment
# zsh inherits. Everything else — anything the user exports from `~/.zshrc` or
# `~/.zprofile` — is unset here, because zsh reads `~/.zshenv` FIRST. Keeping
# the list to these two sources is what makes the warning worth reading: warn
# about `$HOME` too and users learn to ignore it.
#
# Being on this list suppresses the warning, so a wrong entry is a false
# negative in the dangerous direction — the scope silently widens and can select
# credentials everywhere. A missing entry only costs one extra warning, so
# every entry must be verifiable by probing zsh, and anything doubtful stays off.
# "Set but empty" counts as unset: an empty expansion collapses the scope
# exactly like a missing parameter. That is why `TTY` is absent — zsh does set
# it, but to the empty string whenever stdin is not a terminal, which is most
# shells that read `~/.zshenv` (scripts, `zsh -c`, launchd-started processes).
#
# `ZDOTDIR` is absent for two independent reasons: zsh never sets it, and if the
# user has set it, zsh reads `$ZDOTDIR/.zshenv` rather than the `~/.zshenv` that
# `ensure_zshenv_sources` wires up — so this code is not running at all.
# `HOSTNAME` is absent because zsh sets `HOST`, not `HOSTNAME`, and no login
# path (login(1), launchd, sshd) puts `HOSTNAME` in the environment either.
#
# `~` is not on the list because it needs no value: tilde expansion consults the
# password database, so it survives even an unset HOME.
ZSHENV_AVAILABLE_VARS = frozenset({
    # set by zsh before any startup file
    "HOME", "PWD", "OLDPWD", "PATH", "SHLVL", "IFS",
    "ZSH_NAME", "ZSH_VERSION", "UID", "EUID", "GID", "EGID", "PPID",
    "HOST", "LOGNAME", "USERNAME", "OSTYPE", "MACHTYPE", "VENDOR",
    # placed in the inherited environment by login / launchd / sshd / the terminal
    "USER", "SHELL", "TMPDIR", "TERM", "LANG",
})


def unexpandable_scope_vars(match: str) -> list[str]:
    """Variable references in a `project_env` scope that will be empty in
    `~/.zshenv`, in order of first appearance.

    Only `$VAR` / `${VAR}` are recognized — the same forms identity resolution
    expands (`moza.resolve`), so both sides agree on what counts as a reference.
    """
    seen: list[str] = []
    for m in _VAR_RE.finditer(match):
        name = m.group(1) or m.group(2)
        if name not in ZSHENV_AVAILABLE_VARS and name not in seen:
            seen.append(name)
    return seen


def _emit_value(value: str) -> str:
    """Double-quote so zsh expands $HOME / $VAR. Escape only backslash and
    double-quote — the minimum for a well-formed string literal. `$` and
    backticks are intentionally left intact: the value IS evaluated by zsh
    (that is how references work). The config is trusted; `env sync`'s
    `zsh -n` parse-gate guards against a value that breaks syntax."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _scope_block(scope) -> str:
    # match_base is shared with identity resolution so both agree on where a
    # scope ENDS — the trailing '/*' and '/' normalization, and the '/'-separated
    # descendant boundary. They deliberately disagree about expansion: zsh
    # expands the pattern here at match time, while identity resolution leaves an
    # unset or empty reference literal so it fails closed. unexpandable_scope_vars
    # warns about the scopes where that difference bites.
    lines = [f'case "$PWD/" in {match_base(scope.match)}/*)']
    for key in scope.env:  # preserve declared key order
        lines.append(f"  export {key}={_emit_value(scope.env[key])}")
    lines.append(";; esac")
    return "\n".join(lines)


def render_ambient(profiles: dict[str, Profile]) -> str:
    blocks = []
    for name in sorted(profiles):  # deterministic; see plan note on cross-profile order
        for scope in profiles[name].project_env:
            blocks.append(_scope_block(scope))
    body = ("\n".join(blocks) + "\n") if blocks else ""
    return f"{HEADER}\n{body}{FOOTER}\n"


class AmbientParseError(Exception):
    pass


def ambient_path() -> Path:
    return config_path().parent / "ambient.zsh"


def assert_parses(script: str) -> None:
    """Reject a script that zsh cannot parse. `zsh -n` parses without executing.
    If zsh is not installed, skip the check (it can only run where zsh runs)."""
    zsh = shutil.which("zsh")
    if not zsh:
        return
    proc = subprocess.run([zsh, "-n"], input=script, text=True, capture_output=True)
    if proc.returncode != 0:
        raise AmbientParseError(proc.stderr.strip() or "zsh -n rejected the ambient script")


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file in the SAME directory + os.replace (atomic same-fs
    rename), so a reader (every zsh sourcing this file) sees the old or the new
    content, never a partial write left by a disk-full or interrupted process."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_ambient(profiles: dict[str, Profile]) -> Path:
    script = render_ambient(profiles)
    assert_parses(script)               # never write an unparseable file
    path = ambient_path()
    _atomic_write(path, script)
    return path


def ensure_zshenv_sources(zshenv: Path, ambient: Path) -> bool:
    """Idempotently insert/replace a marked region in `zshenv` that sources
    `ambient`. Returns True if the file changed. Existing user content outside
    the marked region is preserved untouched."""
    region = (
        f'{ZSHENV_BEGIN}\n[ -f "{ambient}" ] && source "{ambient}"\n{ZSHENV_END}'
    )
    old = zshenv.read_text() if zshenv.exists() else ""
    pattern = re.compile(re.escape(ZSHENV_BEGIN) + r".*?" + re.escape(ZSHENV_END), re.DOTALL)
    if pattern.search(old):
        new = pattern.sub(lambda _m: region, old, count=1)
    else:
        sep = "" if old == "" or old.endswith("\n") else "\n"
        new = f"{old}{sep}{region}\n"
    if new == old:
        return False
    _atomic_write(zshenv, new)
    return True
