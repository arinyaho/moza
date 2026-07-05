from __future__ import annotations

import os
import secrets as _secrets
from pathlib import Path

from moza.env import EnvBundle

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
    "GIT_SSH_COMMAND",
]


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _env_script_dir() -> Path:
    tmpdir = Path(os.environ.get("TMPDIR", "/tmp"))
    root = tmpdir / "hat"
    root.mkdir(parents=True, exist_ok=True)
    return root


def write_env_script(bundle: EnvBundle) -> Path:
    """Write the bundle's exports into a 0600 ephemeral file and return its path.

    The file is named env-<hex>.sh so EphemeralStore.gc() — which only sweeps
    PID-prefixed files — leaves it alone. The eval'd one-liner unlinks the
    file after sourcing; orphans are swept by `hat doctor --gc`.
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
