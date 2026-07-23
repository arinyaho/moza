import shutil
import subprocess

import pytest
from click.testing import CliRunner

from moza.cli import main
from moza.shell import render_shell_init


def test_render_shell_init_defines_the_wrappers():
    for shell in ("zsh", "bash"):
        script = render_shell_init(shell)
        assert "moza-use()" in script
        assert "moza-unset()" in script
        # The EXIT-trap GC sweeper must be wired in.
        assert "trap __moza_atexit EXIT" in script


def test_shell_init_command_prints_the_script():
    result = CliRunner().invoke(main, ["shell-init"])
    assert result.exit_code == 0, result.output
    assert "moza-use()" in result.output
    assert "moza-unset()" in result.output


def test_shell_init_rejects_an_unknown_shell():
    result = CliRunner().invoke(main, ["shell-init", "--shell", "fish"])
    assert result.exit_code != 0


@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh not available")
def test_zsh_can_source_shell_init_output():
    init = render_shell_init("zsh")
    script = f"{init}\ntype moza-use; type moza-unset"
    out = subprocess.run(["zsh", "-c", script], capture_output=True, text=True, check=True)
    combined = out.stdout + out.stderr
    assert "moza-use" in combined and "moza-unset" in combined
    assert "function" in combined.lower()


def test_bash_can_source_shell_init_output():
    init = render_shell_init("bash")
    script = f"{init}\ntype moza-use; type moza-unset"
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    assert "moza-use is a function" in out.stdout
    assert "moza-unset is a function" in out.stdout
