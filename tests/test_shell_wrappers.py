import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh not available")
def test_zsh_wrapper_defines_functions():
    script = f"source {REPO_ROOT}/shell/hat.zsh; type hat-use; type hat-unset"
    out = subprocess.run(["zsh", "-c", script], capture_output=True, text=True, check=True)
    combined = out.stdout + out.stderr
    assert "hat-use" in combined
    assert "hat-unset" in combined
    # zsh `type` may say "is a shell function" or similar
    assert "function" in combined.lower() or "shell function" in combined.lower()


def test_bash_wrapper_defines_functions():
    script = f"source {REPO_ROOT}/shell/hat.bash; type hat-use; type hat-unset"
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    assert "hat-use is a function" in out.stdout
    assert "hat-unset is a function" in out.stdout
