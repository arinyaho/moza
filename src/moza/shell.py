from __future__ import annotations

import os
import secrets as _secrets
from pathlib import Path

from moza.env import EnvBundle

# The shell wrappers, as one canonical source. `moza shell-init` prints this so a
# user can wire it up with `eval "$(moza shell-init)"` — no repo checkout needed,
# which is the whole point: the CLI installs from a git URL and this comes with
# it. zsh and bash share the body; only the header comment differs.
_SHELL_WRAPPERS = """\
moza-use() {
  if [ -z "$1" ]; then
    echo "usage: moza-use <profile>" >&2
    return 2
  fi
  local exports
  exports="$(command moza use "$1")" || return $?
  eval "$exports"
}

moza-unset() {
  local clears
  clears="$(command moza unset)" || return $?
  eval "$clears"
}

__moza_atexit() {
  if [ -n "$MOZA_PROFILE" ]; then
    command moza doctor --gc >/dev/null 2>&1 || true
  fi
}

trap __moza_atexit EXIT
"""

_SUPPORTED_SHELLS = ("zsh", "bash")


def render_shell_init(shell: str) -> str:
    """The shell wrappers (`moza-use`, `moza-unset`, the exit-trap GC) for eval.

    zsh and bash take the same body — POSIX `[ ]` tests, `local`, and an EXIT
    trap all work in both. Kept as one string so the two cannot drift.
    """
    if shell not in _SUPPORTED_SHELLS:
        raise ValueError(
            f"unsupported shell {shell!r}; expected one of {', '.join(_SUPPORTED_SHELLS)}"
        )
    header = f"# moza shell integration — eval \"$(moza shell-init --shell {shell})\"\n"
    return header + _SHELL_WRAPPERS


KNOWN_VARS = [
    "MOZA_PROFILE",
    "MOZA_EPHEMERAL_DIR",
    "CLOUDSDK_ACTIVE_CONFIG_NAME",
    "CLOUDSDK_CORE_PROJECT",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GH_TOKEN",
    "MOZA_SLACK_TOKENS",
    "MOZA_SLACK_DEFAULT_TOKEN",
    "AWS_PROFILE",
    "AWS_DEFAULT_REGION",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "OCI_CLI_PROFILE",
    "OCI_CLI_CONFIG_FILE",
    "ATLASSIAN_EMAIL",
    "ATLASSIAN_API_TOKEN",
    "ATLASSIAN_BASE_URL",
    "NOTION_TOKEN",
    "GIT_SSH_COMMAND",
]


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _env_script_dir() -> Path:
    tmpdir = Path(os.environ.get("TMPDIR", "/tmp"))
    root = tmpdir / "moza"
    root.mkdir(parents=True, exist_ok=True)
    return root


def write_env_script(bundle: EnvBundle) -> Path:
    """Write the bundle's exports into a 0600 ephemeral file and return its path.

    The file is named env-<hex>.sh so EphemeralStore.gc() — which only sweeps
    PID-prefixed files — leaves it alone. The eval'd one-liner unlinks the
    file after sourcing; orphans are swept by `moza doctor --gc`.
    """
    root = _env_script_dir()
    path = root / f"env-{_secrets.token_hex(8)}.sh"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        body = "".join(
            f"export {k}={_shell_quote(v)}\n" for k, v in bundle.env.items()
        )
        os.write(fd, body.encode("utf-8"))
    finally:
        os.close(fd)
    return path


def emit_use(bundle: EnvBundle) -> str:
    """Emit a shell snippet that loads `bundle`'s exports without printing the
    values to stdout. The exports live in a 0600 ephemeral file; stdout only
    carries the source-and-delete one-liner, so a caller that forgets `eval`
    cannot leak secrets through tool-call transcripts, history, or `ps`.
    """
    path = write_env_script(bundle)
    q = _shell_quote(str(path))
    return f". {q} && rm -f {q}\n"


def emit_unset() -> str:
    return "\n".join(f"unset {v}" for v in KNOWN_VARS) + "\n"
