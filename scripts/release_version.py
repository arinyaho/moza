"""Synchronize Mien's release version across its distributed metadata."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def replace_once(text: str, pattern: re.Pattern[str], version: str, label: str) -> str:
    updated, count = pattern.subn(rf"\g<1>{version}\g<2>", text, count=1)
    if count != 1:
        raise ValueError(f"missing {label} version field")
    return updated


def main() -> None:
    if len(sys.argv) != 2 or not SEMVER_RE.fullmatch(sys.argv[1]):
        raise SystemExit("Usage: python scripts/release_version.py <semver-version>")
    version = sys.argv[1]
    root = Path(os.environ.get("MIEN_VERSION_ROOT", Path(__file__).resolve().parents[1])).resolve()
    version_file = root / "VERSION"
    claude_manifest = root / "plugins/mien/.claude-plugin/plugin.json"
    codex_manifest = root / "plugins/mien/.codex-plugin/plugin.json"
    pyproject = root / "pyproject.toml"
    skill = root / "plugins/mien/skills/mien/SKILL.md"
    files = [version_file, claude_manifest, codex_manifest, pyproject, skill]

    # Read and validate every target before changing any one of them.
    contents = {file: file.read_text(encoding="utf-8") for file in files}
    for manifest in (claude_manifest, codex_manifest):
        json.loads(contents[manifest])
    for file in files:
        if not os.access(file, os.W_OK):
            raise PermissionError(f"not writable: {file}")

    replacements = {
        claude_manifest: replace_once(
            contents[claude_manifest],
            re.compile(r'("version"\s*:\s*")(?:(?:\\.)|[^"\\])*(")'),
            version,
            "JSON",
        ),
        codex_manifest: replace_once(
            contents[codex_manifest],
            re.compile(r'("version"\s*:\s*")(?:(?:\\.)|[^"\\])*(")'),
            version,
            "JSON",
        ),
        pyproject: replace_once(
            contents[pyproject], re.compile(r'^(version\s*=\s*")[^"]*(")', re.MULTILINE), version, "pyproject"
        ),
        skill: replace_once(
            contents[skill], re.compile(r'^(version:\s*)\S+($)', re.MULTILINE), version, "skill"
        ),
    }
    version_file.write_text(f"{version}\n", encoding="utf-8")
    for file, content in replacements.items():
        file.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
