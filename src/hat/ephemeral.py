from __future__ import annotations

import contextlib
import os
import re
from pathlib import Path


class EphemeralStore:
    def __init__(self, pid: int | None = None) -> None:
        self.pid = pid if pid is not None else os.getpid()
        tmpdir = Path(os.environ.get("TMPDIR", "/tmp"))
        self.root = tmpdir / "hat"

    def write(self, *, profile: str, kind: str, data: bytes) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{self.pid}-{profile}-{kind}.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        return path

    def cleanup(self) -> None:
        if not self.root.exists():
            return
        for p in self.root.iterdir():
            if p.is_file() and p.name.startswith(f"{self.pid}-"):
                with contextlib.suppress(FileNotFoundError):
                    p.unlink()

    @classmethod
    def gc(cls) -> None:
        tmpdir = Path(os.environ.get("TMPDIR", "/tmp"))
        root = tmpdir / "hat"
        if not root.exists():
            return
        pat = re.compile(r"^(\d+)-")
        for p in root.iterdir():
            if not p.is_file():
                continue
            m = pat.match(p.name)
            if not m:
                continue
            pid = int(m.group(1))
            if not _pid_alive(pid):
                with contextlib.suppress(FileNotFoundError):
                    p.unlink()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
