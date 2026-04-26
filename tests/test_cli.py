import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from hat.cli import main


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def hat_cfg(monkeypatch, tmp_path):
    p = tmp_path / "hat.json"
    monkeypatch.setenv("HAT_CONFIG", str(p))
    return p


def test_list_no_config(runner, hat_cfg):
    result = runner.invoke(main, ["list"])
    assert result.exit_code != 0
    assert "hat init" in result.output


def test_status_when_unset(runner, hat_cfg, monkeypatch):
    monkeypatch.delenv("HAT_PROFILE", raising=False)
    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0
    assert "no profile active" in result.output.lower()


def test_status_active(runner, hat_cfg, monkeypatch):
    monkeypatch.setenv("HAT_PROFILE", "personal")
    result = runner.invoke(main, ["status"])
    assert "personal" in result.output


def test_init_writes_keychain_skeleton(runner, hat_cfg):
    result = runner.invoke(main, ["init"], input="3\nhat-\n")
    assert result.exit_code == 0, result.output
    payload = json.loads(hat_cfg.read_text())
    assert payload["secrets_backend"]["type"] == "macos_keychain"
    assert payload["profiles"] == {}


def test_list_after_init(runner, hat_cfg):
    runner.invoke(main, ["init"], input="3\nhat-\n")
    result = runner.invoke(main, ["list"])
    assert result.exit_code == 0
    assert "no profiles" in result.output.lower()


def test_whoami_unknown_profile(runner, hat_cfg):
    runner.invoke(main, ["init"], input="3\nhat-\n")
    result = runner.invoke(main, ["whoami", "nope"])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()
