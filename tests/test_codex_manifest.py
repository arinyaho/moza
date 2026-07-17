import json
import re
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
    assert claude == codex == proj == skill, (
        f"version drift: claude={claude} codex={codex} pyproject={proj} skill={skill}"
    )
