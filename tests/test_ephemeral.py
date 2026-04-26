import os
from pathlib import Path

import pytest

from hat.ephemeral import EphemeralStore


def test_root_uses_tmpdir(monkeypatch, tmp_path):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    s = EphemeralStore(pid=1234)
    assert s.root == tmp_path / "hat"


def test_write_creates_mode_0600_file(monkeypatch, tmp_path):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    s = EphemeralStore(pid=4242)
    p = s.write(profile="personal", kind="adc", data=b'{"k":"v"}')
    assert p.exists()
    assert (p.stat().st_mode & 0o777) == 0o600
    assert p.read_bytes() == b'{"k":"v"}'
    assert "4242" in p.name and "personal" in p.name and "adc" in p.name


def test_cleanup_removes_pid_files(monkeypatch, tmp_path):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    s = EphemeralStore(pid=4242)
    s.write(profile="p", kind="adc", data=b"x")
    s.write(profile="p", kind="slack", data=b"y")
    assert any(tmp_path.glob("hat/4242-*"))
    s.cleanup()
    assert not any(tmp_path.glob("hat/4242-*"))


def test_gc_removes_files_for_dead_pids(monkeypatch, tmp_path):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    alive = os.getpid()
    dead = 99999998
    EphemeralStore(pid=alive).write(profile="a", kind="adc", data=b"a")
    EphemeralStore(pid=dead).write(profile="b", kind="adc", data=b"b")

    EphemeralStore.gc()

    survivors = list((tmp_path / "hat").iterdir())
    assert any(str(alive) in p.name for p in survivors)
    assert not any(str(dead) in p.name for p in survivors)
