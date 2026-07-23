import re
from pathlib import Path

from moza.env import EnvBundle
from moza.shell import emit_unset, emit_use


def _parse_script_path(out: str) -> Path:
    """`emit_use` returns `. '<path>' && rm -f '<path>'`. Extract path."""
    m = re.match(r"\. '([^']+)' && rm -f '\1'", out.strip())
    assert m, f"unexpected emit_use output: {out!r}"
    return Path(m.group(1))


def test_emit_use_does_not_leak_secrets_to_stdout(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    bundle = EnvBundle(
        profile_name="personal",
        env={
            "MOZA_PROFILE": "personal",
            "GH_TOKEN": "ghp_xx'yy",
            "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/moza/x y.json",
        },
        ephemeral_files=[Path("/tmp/moza/x y.json")],
    )
    out = emit_use(bundle)

    # Critical: the secret value must never appear on stdout. The whole point
    # of routing exports through a 0600 file is that a caller who forgets to
    # `eval` doesn't leak the token to their transcript / history / ps output.
    assert "ghp_xx" not in out
    assert "ghp_xx'yy" not in out

    # The emitted snippet sources a path inside our TMPDIR.
    path = _parse_script_path(out)
    assert path.is_file()
    assert str(path).startswith(str(tmp_path))


def test_emit_use_writes_exports_to_a_0600_env_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    bundle = EnvBundle(
        profile_name="personal",
        env={
            "MOZA_PROFILE": "personal",
            "GH_TOKEN": "ghp_xx'yy",
            "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/moza/x y.json",
        },
    )
    out = emit_use(bundle)
    path = _parse_script_path(out)

    # mode bits must be owner-only (0o600) so other users on the box can't read.
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600, oct(mode)

    body = path.read_text()
    assert "export MOZA_PROFILE='personal'" in body
    assert "GH_TOKEN='ghp_xx'\"'\"'yy'" in body
    assert "GOOGLE_APPLICATION_CREDENTIALS='/tmp/moza/x y.json'" in body


def test_emit_use_scrubs_stale_vars_before_exporting(tmp_path, monkeypatch):
    """Switching profiles must not leave the previous profile's variables set.
    The sourced script unsets every KNOWN_VARS name before exporting only what
    the new profile defines, so a var the new profile omits (here AWS_* and
    ATLASSIAN_*) is cleared rather than left dangling from an earlier `moza use`.
    The unset must precede the exports, or it would wipe the values it just set."""
    from moza.shell import KNOWN_VARS
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    bundle = EnvBundle(
        profile_name="personal",
        env={"MOZA_PROFILE": "personal", "GH_TOKEN": "ghp_new"},
    )
    body = _parse_script_path(emit_use(bundle)).read_text()

    scrub_line = next(ln for ln in body.splitlines() if ln.startswith("unset "))
    scrubbed = set(scrub_line.removeprefix("unset ").split())
    # Every known var is unset up front...
    assert set(KNOWN_VARS) == scrubbed
    # ...including ones this profile does not define (would be stale otherwise).
    assert {"AWS_ACCESS_KEY_ID", "ATLASSIAN_API_TOKEN"} <= scrubbed
    # ...and the unset happens before any export, so set values survive.
    assert body.index("unset ") < body.index("export "), body
    assert "export GH_TOKEN='ghp_new'" in body


def test_emit_unset_lists_known_vars():
    out = emit_unset()
    for var in [
        "MOZA_PROFILE",
        "MOZA_EPHEMERAL_DIR",
        "CLOUDSDK_ACTIVE_CONFIG_NAME",
        "CLOUDSDK_CORE_PROJECT",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GH_TOKEN",
        "MOZA_SLACK_TOKENS",
        "MOZA_SLACK_DEFAULT_TOKEN",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
    ]:
        assert f"unset {var}" in out


def test_known_vars_includes_atlassian():
    from moza.shell import KNOWN_VARS
    assert "ATLASSIAN_EMAIL" in KNOWN_VARS
    assert "ATLASSIAN_API_TOKEN" in KNOWN_VARS
    assert "ATLASSIAN_BASE_URL" in KNOWN_VARS


def test_known_vars_includes_notion():
    from moza.shell import KNOWN_VARS
    assert "NOTION_TOKEN" in KNOWN_VARS
