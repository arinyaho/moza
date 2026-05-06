from __future__ import annotations

from hat.env import EnvBundle

KNOWN_VARS = [
    "HAT_PROFILE",
    "HAT_EPHEMERAL_DIR",
    "CLOUDSDK_ACTIVE_CONFIG_NAME",
    "CLOUDSDK_CORE_PROJECT",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GH_TOKEN",
    "HAT_SLACK_TOKENS",
    "HAT_SLACK_DEFAULT_TOKEN",
]


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def emit_use(bundle: EnvBundle) -> str:
    lines = [f"export {k}={_shell_quote(v)}" for k, v in bundle.env.items()]
    return "\n".join(lines) + "\n"


def emit_unset() -> str:
    return "\n".join(f"unset {v}" for v in KNOWN_VARS) + "\n"
