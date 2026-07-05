from __future__ import annotations

import contextlib
import os
import re
import time
from pathlib import Path

ENV_SCRIPT_MAX_AGE_SEC = 300


class EphemeralStore:
    def __init__(self, pid: int | None = None) -> None:
        self.pid = pid if pid is not None else os.getpid()
        tmpdir = Path(os.environ.get("TMPDIR", "/tmp"))
        self.root = tmpdir / "moza"

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
        root = tmpdir / "moza"
        if not root.exists():
            return
        pid_pat = re.compile(r"^(\d+)-")
        env_pat = re.compile(r"^env-[0-9a-f]+\.sh$")
        now = time.time()
        for p in root.iterdir():
            if not p.is_file():
                continue
            if env_pat.match(p.name):
                # Orphaned env loader from a `hat use` whose eval never ran.
                # Sweep when the file is old enough that no legitimate eval
                # could still be pending.
                try:
                    if now - p.stat().st_mtime > ENV_SCRIPT_MAX_AGE_SEC:
                        p.unlink()
                except FileNotFoundError:
                    pass
                continue
            m = pid_pat.match(p.name)
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
