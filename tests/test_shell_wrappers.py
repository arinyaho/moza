import shutil
import subprocess

import pytest
from click.testing import CliRunner

from mien.cli import main
from mien.shell import render_shell_init


def test_render_shell_init_defines_the_wrappers():
    for shell in ("zsh", "bash"):
        script = render_shell_init(shell)
        assert "mien-use()" in script
        assert "mien-unset()" in script
        # The EXIT-trap GC sweeper must be wired in.
        assert "trap __mien_atexit EXIT" in script


def test_mien_use_wrapper_passes_the_owner_pid():
    """The wrapper is the load-bearing link for persistent human shells: it must
    invoke `mien use --owner-pid $$` so the ephemeral files are keyed to the
    calling shell, not mien's already-exited process. Dropping `--owner-pid $$`
    from the wrapper reintroduces the gc-reclaims-live-credentials bug while every
    other test stays green (the CLI tests pass an explicit pid), so pin it here."""
    for shell in ("zsh", "bash"):
        script = render_shell_init(shell)
        assert "command mien use --owner-pid $$" in script


def test_shell_init_command_prints_the_script():
    result = CliRunner().invoke(main, ["shell-init"])
    assert result.exit_code == 0, result.output
    assert "mien-use()" in result.output
    assert "mien-unset()" in result.output


def test_shell_init_rejects_an_unknown_shell():
    result = CliRunner().invoke(main, ["shell-init", "--shell", "fish"])
    assert result.exit_code != 0


@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh not available")
def test_zsh_can_source_shell_init_output():
    init = render_shell_init("zsh")
    script = f"{init}\ntype mien-use; type mien-unset"
    out = subprocess.run(["zsh", "-c", script], capture_output=True, text=True, check=True)
    combined = out.stdout + out.stderr
    assert "mien-use" in combined and "mien-unset" in combined
    assert "function" in combined.lower()


def test_bash_can_source_shell_init_output():
    init = render_shell_init("bash")
    script = f"{init}\ntype mien-use; type mien-unset"
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    assert "mien-use is a function" in out.stdout
    assert "mien-unset is a function" in out.stdout
