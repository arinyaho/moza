from pathlib import Path

from hat.env import EnvBundle
from hat.shell import emit_unset, emit_use


def test_emit_use_quotes_values():
    bundle = EnvBundle(
        profile_name="personal",
        env={
            "HAT_PROFILE": "personal",
            "GH_TOKEN": "ghp_xx'yy",
            "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/hat/x y.json",
        },
        ephemeral_files=[Path("/tmp/hat/x y.json")],
    )
    out = emit_use(bundle)
    assert "export HAT_PROFILE='personal'" in out
    assert "GH_TOKEN='ghp_xx'\"'\"'yy'" in out
    assert "GOOGLE_APPLICATION_CREDENTIALS='/tmp/hat/x y.json'" in out


def test_emit_unset_lists_known_vars():
    out = emit_unset()
    for var in [
        "HAT_PROFILE",
        "HAT_EPHEMERAL_DIR",
        "CLOUDSDK_ACTIVE_CONFIG_NAME",
        "CLOUDSDK_CORE_PROJECT",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GH_TOKEN",
        "HAT_SLACK_TOKENS",
        "HAT_SLACK_DEFAULT_TOKEN",
    ]:
        assert f"unset {var}" in out
