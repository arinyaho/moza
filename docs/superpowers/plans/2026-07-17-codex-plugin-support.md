# Codex Plugin Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `moza` plugin installable and runnable in the Codex CLI from the same repo that already packages it for Claude Code.

**Architecture:** Add a Codex marketplace manifest at `.agents/plugins/marketplace.json` (Codex's own manifest location, distinct from Claude's `.claude-plugin/marketplace.json`) that lists the existing `plugins/moza` plugin. Fix the drifted SKILL.md version and lock all manifests with a validation test. Verify install + skill trigger in a real Codex session.

**Tech Stack:** Codex CLI (`codex plugin marketplace add` / `codex plugin add`), JSON manifests, Python + pytest (`uv run pytest`).

## Global Constraints

- Version across all four version-bearing files MUST equal `0.5.0`: `plugins/moza/.claude-plugin/plugin.json`, `plugins/moza/.codex-plugin/plugin.json`, `pyproject.toml`, `plugins/moza/skills/moza/SKILL.md`.
- Codex marketplace `name` MUST be `arinyaho` (matches the existing Claude marketplace identity); install target is therefore `moza@arinyaho`.
- Do NOT modify the Claude-side manifests or the skill body logic. Only SKILL.md's `version:` field changes.
- Codex plugin `source` paths are repo-root-relative: `./plugins/moza`.
- DoD (`review.config.json`): `uv run pytest -q` must pass.

## Codex contract (resolved — do not re-investigate)

- Manifest file: `<repo-root>/.agents/plugins/marketplace.json`.
- Schema: `{ "name": <str>, "interface": { "displayName": <str> }, "plugins": [ { "name", "source": {"source":"local","path":"./plugins/<x>"}, "policy": {"installation","authentication","products":["CODEX"]}, "category" } ] }`.
- Register a Git marketplace: `codex plugin marketplace add <owner/repo>[@ref] [--ref <ref>]`; local: `codex plugin marketplace add <path>`. The marketplace name is read from the manifest `name` field, not the CLI arg.
- Install a plugin: `codex plugin add <plugin>@<marketplace>`. List: `codex plugin list`. Remove marketplace: `codex plugin marketplace remove <name>`.

---

### Task 1: Codex marketplace manifest

**Files:**
- Create: `.agents/plugins/marketplace.json`

**Interfaces:**
- Produces: the file `.agents/plugins/marketplace.json` with marketplace `name: "arinyaho"` and a plugin entry `name: "moza"`, `source.path: "./plugins/moza"`. Task 2's test reads these.

- [ ] **Step 1: Create the Codex marketplace manifest**

Create `.agents/plugins/marketplace.json`:

```json
{
  "name": "arinyaho",
  "interface": {
    "displayName": "moza"
  },
  "plugins": [
    {
      "name": "moza",
      "source": {
        "source": "local",
        "path": "./plugins/moza"
      },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL",
        "products": [
          "CODEX"
        ]
      },
      "category": "Developer Tools"
    }
  ]
}
```

- [ ] **Step 2: Validate the manifest parses and Codex accepts it (local add)**

Run:

```bash
codex plugin marketplace add "$PWD" && codex plugin list
```

Expected: the `add` succeeds and `codex plugin list` shows a `moza` row under marketplace `arinyaho`. If `add` errors on schema, fix the manifest to match the error and re-run.

- [ ] **Step 3: Clean up the throwaway local marketplace source**

Run:

```bash
codex plugin marketplace remove arinyaho
```

Expected: removes the local source (the real registration happens from Git in Task 3). If it reports the plugin is still installed, that is fine — this only detaches the local marketplace snapshot.

- [ ] **Step 4: Commit**

```bash
git add .agents/plugins/marketplace.json
git commit -m "feat(codex): add Codex marketplace manifest listing moza"
```

---

### Task 2: Version-sync test + SKILL.md fix (TDD)

**Files:**
- Create: `tests/test_codex_manifest.py`
- Modify: `plugins/moza/skills/moza/SKILL.md:4`

**Interfaces:**
- Consumes: `.agents/plugins/marketplace.json` from Task 1; the existing `plugins/moza/.codex-plugin/plugin.json`, `plugins/moza/.claude-plugin/plugin.json`, `pyproject.toml`, `plugins/moza/skills/moza/SKILL.md`.
- Produces: a pytest module locking manifest validity + four-file version sync.

- [ ] **Step 1: Write the test (test-first — the sync test will fail on the drifted SKILL.md)**

Create `tests/test_codex_manifest.py`:

```python
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
```

- [ ] **Step 2: Run the test — the sync test must fail on the drifted SKILL.md**

Run:

```bash
uv run pytest tests/test_codex_manifest.py -q
```

Expected: `test_version_in_sync_across_all_manifests` FAILS with `version drift: claude=0.5.0 codex=0.5.0 pyproject=0.5.0 skill=0.3.0`. The other two tests PASS.

- [ ] **Step 3: Fix the SKILL.md version drift**

In `plugins/moza/skills/moza/SKILL.md`, change line 4 from:

```
version: 0.3.0
```

to:

```
version: 0.5.0
```

- [ ] **Step 4: Run the test — all pass**

Run:

```bash
uv run pytest tests/test_codex_manifest.py -q
```

Expected: 3 passed.

- [ ] **Step 5: Run the full suite (DoD)**

Run:

```bash
uv run pytest -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add tests/test_codex_manifest.py plugins/moza/skills/moza/SKILL.md
git commit -m "test(codex): lock manifest validity + four-file version sync; fix SKILL.md drift"
```

---

### Task 3: Real Codex install + parity verification + docs

**Files:**
- Modify: `README.md` (add an "Install in Codex" section next to the existing Claude install instructions)

**Interfaces:**
- Consumes: the committed marketplace manifest; a pushed branch/ref reachable by `codex plugin marketplace add`.

- [ ] **Step 1: Register the marketplace from the current branch and install moza**

Run (push the branch first if the ref is not yet on the remote):

```bash
codex plugin marketplace add arinyaho/moza --ref feat/codex-plugin-support
codex plugin add moza@arinyaho
codex plugin list
```

Expected: `moza@arinyaho` appears installed/enabled in `codex plugin list`. If `add` cannot see the manifest, confirm `.agents/plugins/marketplace.json` is present at the fetched ref.

- [ ] **Step 2: Parity check — trigger the skill in a real Codex session**

Run a non-interactive Codex exec that should trigger the moza skill:

```bash
codex exec "switch to my personal moza identity, then run: moza list"
```

Expected observations (record them; this is a manual gate, not an assertion):
- Codex loads the `moza` skill (references its SKILL.md guidance).
- The skill resolves the `moza` binary from PATH (or the source fallback) and runs a `moza` command.
- No Claude-specific tool/harness error surfaces. If the binary is unresolved, note whether SKILL.md's resolution block needs a Codex-friendly path; fix only if actually broken.

- [ ] **Step 3: Add the "Install in Codex" README section**

In `README.md`, directly after the existing Claude `## Install` block, add:

```markdown
### Install in Codex

```bash
codex plugin marketplace add arinyaho/moza --ref main
codex plugin add moza@arinyaho
```

Then trigger it in any Codex session — e.g. "switch to my work account".
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: add Codex install instructions"
```

---

## Self-Review

- **Spec coverage:** Phase 0 (contract) — resolved and captured in "Codex contract" above; no task needed. Phase 1 (marketplace listing + manifest audit + SKILL.md fix) — Task 1 + Task 2 Step 3. Phase 2 (install + parity) — Task 3 Steps 1-2. Phase 3 (tests + docs) — Task 2 (test) + Task 3 Step 3 (docs). Success criteria: install (Task 3 S1), skill runs (Task 3 S2), version sync + Claude path covered (Task 2 test). All covered.
- **Placeholder scan:** none — every step has exact file content or command + expected output.
- **Type/name consistency:** marketplace `name` `arinyaho`, plugin `name` `moza`, `source.path` `./plugins/moza`, version `0.5.0` — used identically in the manifest (Task 1) and the test (Task 2).
- **Note:** Task 3 Step 2 is a manual observation gate (real Codex session behavior can't be a unit assertion); it is explicitly marked as such.
