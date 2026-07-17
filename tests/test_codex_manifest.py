import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read_json(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def _skill_md_version() -> str:
    text = (ROOT / "plugins/moza/skills/moza/SKILL.md").read_text(encoding="utf-8")
    m = re.search(r"^version:\s*(\S+)", text, re.MULTILINE)
    assert m, "SKILL.md is missing a `version:` frontmatter field"
    return m.group(1)


def _pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert m, "pyproject.toml is missing a version"
    return m.group(1)


def test_codex_marketplace_manifest_valid():
    m = _read_json(".agents/plugins/marketplace.json")
    assert m["name"] == "arinyaho"
    assert isinstance(m["interface"]["displayName"], str) and m["interface"]["displayName"]
    plugins = {p["name"]: p for p in m["plugins"]}
    assert "moza" in plugins, "marketplace must list a plugin named 'moza'"
    moza = plugins["moza"]
    assert moza["source"] == {"source": "local", "path": "./plugins/moza"}
    assert moza["policy"]["products"] == ["CODEX"]
    # the source path resolves to a real Codex plugin directory
    assert (ROOT / "plugins/moza/.codex-plugin/plugin.json").is_file()


def test_codex_plugin_skills_path_exists():
    p = _read_json("plugins/moza/.codex-plugin/plugin.json")
    skills = p["skills"]  # e.g. "./skills/"
    assert (ROOT / "plugins/moza" / skills.lstrip("./")).is_dir()


def test_version_in_sync_across_all_manifests():
    claude = _read_json("plugins/moza/.claude-plugin/plugin.json")["version"]
    codex = _read_json("plugins/moza/.codex-plugin/plugin.json")["version"]
    proj = _pyproject_version()
    skill = _skill_md_version()
    shared = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert claude == codex == proj == skill == shared, (
        "version drift: "
        f"claude={claude} codex={codex} pyproject={proj} skill={skill} shared={shared}"
    )


def test_release_version_updates_an_isolated_version_and_all_consumers():
    script = ROOT / "scripts/release_version.py"
    with tempfile.TemporaryDirectory(prefix="moza-version-") as temp_dir:
        root = Path(temp_dir)
        (root / "plugins/moza/.claude-plugin").mkdir(parents=True)
        (root / "plugins/moza/.codex-plugin").mkdir(parents=True)
        (root / "plugins/moza/skills/moza").mkdir(parents=True)
        (root / "VERSION").write_text("0.1.0-alpha.1\n", encoding="utf-8")
        (root / "plugins/moza/.claude-plugin/plugin.json").write_text(
            '{\n  "name": "moza",\n  "version": "0.1.0-alpha.1",\n  "preserve": true\n}\n',
            encoding="utf-8",
        )
        (root / "plugins/moza/.codex-plugin/plugin.json").write_text(
            '{"name":"moza","version":"0.1.0-alpha.1","nested":{"version":"keep"}}\n',
            encoding="utf-8",
        )
        (root / "pyproject.toml").write_text(
            '[project]\nname = "moza"\nversion = "0.1.0-alpha.1"\n',
            encoding="utf-8",
        )
        (root / "plugins/moza/skills/moza/SKILL.md").write_text(
            '---\nname: moza\nversion: 0.1.0-alpha.1\n---\n', encoding="utf-8"
        )

        subprocess.run(
            [sys.executable, str(script), "0.5.0"],
            check=True,
            cwd=root,
            env={**os.environ, "MOZA_VERSION_ROOT": str(root)},
            capture_output=True,
            text=True,
        )

        assert (root / "VERSION").read_text(encoding="utf-8") == "0.5.0\n"
        assert _read_fixture_json(root, "plugins/moza/.claude-plugin/plugin.json") == {
            "name": "moza", "version": "0.5.0", "preserve": True
        }
        assert (root / "plugins/moza/.codex-plugin/plugin.json").read_text(encoding="utf-8") == (
            '{"name":"moza","version":"0.5.0","nested":{"version":"keep"}}\n'
        )
        assert 'version = "0.5.0"' in (root / "pyproject.toml").read_text(encoding="utf-8")
        assert 'version: 0.5.0' in (root / "plugins/moza/skills/moza/SKILL.md").read_text(encoding="utf-8")


def test_release_version_does_not_partially_update_when_a_target_is_missing():
    script = ROOT / "scripts/release_version.py"
    with tempfile.TemporaryDirectory(prefix="moza-version-") as temp_dir:
        root = Path(temp_dir)
        (root / "plugins/moza/.claude-plugin").mkdir(parents=True)
        (root / "VERSION").write_text("0.1.0\n", encoding="utf-8")
        claude = root / "plugins/moza/.claude-plugin/plugin.json"
        original = '{"name":"moza","version":"0.1.0"}\n'
        claude.write_text(original, encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(script), "0.5.0"],
            cwd=root,
            env={**os.environ, "MOZA_VERSION_ROOT": str(root)},
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        assert (root / "VERSION").read_text(encoding="utf-8") == "0.1.0\n"
        assert claude.read_text(encoding="utf-8") == original


def _read_fixture_json(root: Path, relative_path: str) -> dict:
    return json.loads((root / relative_path).read_text(encoding="utf-8"))
