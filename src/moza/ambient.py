from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from moza.config import Profile, config_path

HEADER = "# >>> moza ambient env (generated — do not edit; run `moza env sync`) >>>"
FOOTER = "# <<< moza ambient env <<<"

ZSHENV_BEGIN = "# >>> moza ambient (zshenv) >>>"
ZSHENV_END = "# <<< moza ambient (zshenv) <<<"


def _emit_value(value: str) -> str:
    """Double-quote so zsh expands $HOME / $VAR. Escape only backslash and
    double-quote — the minimum for a well-formed string literal. `$` and
    backticks are intentionally left intact: the value IS evaluated by zsh
    (that is how references work). The config is trusted; `env sync`'s
    `zsh -n` parse-gate guards against a value that breaks syntax."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _match_base(match: str) -> str:
    """Directory-root glob: strip a trailing '/*' or '/' so the scope matches
    the directory itself AND everything under it when tested against "$PWD/"."""
    base = match
    if base.endswith("/*"):
        base = base[:-2]
    return base.rstrip("/")


def _scope_block(scope) -> str:
    lines = [f'case "$PWD/" in {_match_base(scope.match)}/*)']
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


def write_ambient(profiles: dict[str, Profile]) -> Path:
    script = render_ambient(profiles)
    assert_parses(script)               # never write an unparseable file
    path = ambient_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(script)
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
    zshenv.parent.mkdir(parents=True, exist_ok=True)
    zshenv.write_text(new)
    return True
