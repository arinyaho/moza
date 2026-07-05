# Rename `hat` → `moza` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the Python package, CLI binary, env vars, config/tmp paths,
shell wrappers, backend secret-naming, and all docs from `hat` to `moza`, leaving
the repo with zero `hat` references (this-repo scope), plus a one-time throwaway
migration script deleted before merge.

**Architecture:** Pure mechanical rename executed as ordered tasks, each keeping
the full `pytest` suite green. Code identity changes first (package + imports),
then user-facing strings (env vars, paths, secret names), then docs/versions,
then a standalone migration script run once locally, then a machine cutover
(`mv` the clone dir, swap the uv tool) and a final sha-pinning commit.

**Tech Stack:** Python 3.11, click, uv (tool install), pytest, hatchling build.

Spec: `docs/superpowers/specs/2026-07-05-rename-hat-to-moza-design.md`.
Branch: `refactor/rename-hat-to-moza` (already checked out; execute in-place —
the rename moves this very clone dir in Task 8, so do NOT use a separate
worktree).

## Global Constraints

- **Surgical rename — never blind-`sed` the word `hat`.** These MUST survive:
  `hatchling` (build backend), `[tool.hatch.build.targets.wheel]`. A
  `git grep -nwi hat` does not match them (word boundary), but any replace must
  still be scoped to the intended tokens.
- **Zero-legacy scope = this repo only.** External refs (chemcopilot repo,
  Claude memories, `~/.zshrc`) are out of scope except the two sanctioned
  machine steps in Task 8.
- **Versions unify to `0.3.0`**: `pyproject.toml`, both plugin manifests.
- **Install stays non-editable** (`uv tool install .`, a copy). Never
  `pip install -e .` — editable couples the entry point to the source path and
  breaks the Task 8 `mv`.
- **Migration script** (`scripts/migrate_from_hat.py`) is excluded from the
  wheel and deleted in the final pre-merge commit. It must NOT call
  `pull_manifest`/`push_manifest` (they hardcode the new manifest name); read
  the old `hat-config-manifest` at backend-primitive level. Read old config via
  `Path.home() / ".config/hat/config.json"` (never a literal `"~/..."` to
  `open()`).
- **Every task ends green:** `pytest tests/` passes, then commit.
- **Test-string rule:** when a task renames a runtime string (env var, path,
  secret template), update the tests that assert the OLD string in the SAME task
  so the suite is green at the task boundary.

---

### Task 1: Package + CLI identity (`src/hat` → `src/moza`, imports, packaging)

Rename ONLY the package/module identity and the distribution/entry-point. Do
NOT touch env-var strings (`HAT_*`), on-disk paths (`~/.config/hat`), or secret
templates (`hat-*`) yet — those are later tasks and the current tests still
assert them.

**Files:**
- Move: `src/hat/` → `src/moza/` (all 13 modules)
- Modify: every `*.py` under `src/` and `tests/` with `from hat`/`import hat`
- Modify: `pyproject.toml` (name, scripts, wheel packages)
- Modify: `src/moza/cli.py:96` (`version_option(package_name=...)`)
- Modify: `src/moza/__main__.py` (`python -m hat` comment, if present)

**Interfaces:**
- Produces: import root `moza` (`from moza.config import ...`), binary `moza`,
  dist name `moza`. All later tasks import from `moza`.

- [ ] **Step 1: Move the package directory**

```bash
cd ~/Projects/hat
git mv src/hat src/moza
```

- [ ] **Step 2: Rewrite Python imports (package identity only)**

Rewrite import statements across `src/` and `tests/`. These patterns are the
only module-context uses of `hat`; env vars / paths / secret names are NOT
touched (different casing/shape).

```bash
grep -rlE '(from|import) hat(\.|$| )' src tests | while read -r f; do
  perl -pi -e 's/\bfrom hat\b/from moza/g; s/\bimport hat\b/import moza/g' "$f"
done
# module-qualified refs like `hat.cli:main` live only in pyproject (Step 4)
grep -rn 'python -m hat\b' src && perl -pi -e 's/python -m hat\b/python -m moza/g' src/moza/__main__.py || true
```

- [ ] **Step 3: Verify no `hat` import survives**

Run: `grep -rnE '\b(from|import) hat\b' src tests`
Expected: no output.

- [ ] **Step 4: Update `pyproject.toml`**

Change exactly these three lines (leave `hatchling` / `[tool.hatch...]` intact):

```toml
name = "moza"
# [project.scripts]
moza = "moza.cli:main"
# [tool.hatch.build.targets.wheel]
packages = ["src/moza"]
```

- [ ] **Step 5: Update the version-option package name**

In `src/moza/cli.py:96`, change `package_name="hat-cli"` → `package_name="moza"`.

- [ ] **Step 6: Uninstall old tool, install new (non-editable)**

```bash
uv tool uninstall hat-cli
uv tool install .
command -v hat    # expect: empty (exit 1)
command -v moza   # expect: ~/.local/bin/moza
moza --version    # expect: moza, version 0.1.0
```

- [ ] **Step 7: Run the full suite**

Run: `pytest tests/ -q`
Expected: all pass (only imports changed; runtime strings unchanged).

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: rename package hat → moza (imports, entry point)"
```

---

### Task 2: Runtime env vars `HAT_*` → `MOZA_*`

**Files:**
- Modify: `src/moza/config.py` (`HAT_CONFIG`)
- Modify: `src/moza/env.py` (`HAT_PROFILE`, `HAT_EPHEMERAL_DIR`,
  `HAT_SLACK_TOKENS`, `HAT_SLACK_DEFAULT_TOKEN`)
- Modify: `src/moza/shell.py` (`KNOWN_VARS` list)
- Modify: `src/moza/cli.py` (any `HAT_PROFILE` reads, e.g. `token` cmd)
- Modify: `src/moza/ephemeral.py` (if it reads `HAT_*`)
- Modify tests: `tests/test_env.py`, `tests/test_shell.py`, `tests/test_cli.py`
  (fixture `hat_cfg` sets `HAT_CONFIG` → `MOZA_CONFIG`)
- Docs (env-var mentions only, full doc pass is Task 6): none required for green

**Interfaces:**
- Produces: env vars `MOZA_CONFIG`, `MOZA_PROFILE`, `MOZA_EPHEMERAL_DIR`,
  `MOZA_SLACK_TOKENS`, `MOZA_SLACK_DEFAULT_TOKEN`.

- [ ] **Step 1: Rewrite the 5 env-var identifiers in `src/`**

```bash
grep -rl 'HAT_' src | while read -r f; do
  perl -pi -e 's/\bHAT_CONFIG\b/MOZA_CONFIG/g;
               s/\bHAT_PROFILE\b/MOZA_PROFILE/g;
               s/\bHAT_EPHEMERAL_DIR\b/MOZA_EPHEMERAL_DIR/g;
               s/\bHAT_SLACK_TOKENS\b/MOZA_SLACK_TOKENS/g;
               s/\bHAT_SLACK_DEFAULT_TOKEN\b/MOZA_SLACK_DEFAULT_TOKEN/g' "$f"
done
grep -rn 'HAT_' src   # expect: no output
```

- [ ] **Step 2: Update the tests that assert the old names**

Apply the same 5 substitutions to `tests/`:

```bash
grep -rl 'HAT_' tests | while read -r f; do
  perl -pi -e 's/\bHAT_CONFIG\b/MOZA_CONFIG/g;
               s/\bHAT_PROFILE\b/MOZA_PROFILE/g;
               s/\bHAT_EPHEMERAL_DIR\b/MOZA_EPHEMERAL_DIR/g;
               s/\bHAT_SLACK_TOKENS\b/MOZA_SLACK_TOKENS/g;
               s/\bHAT_SLACK_DEFAULT_TOKEN\b/MOZA_SLACK_DEFAULT_TOKEN/g' "$f"
done
grep -rn 'HAT_' tests   # expect: no output
```

- [ ] **Step 3: Run the suite**

Run: `pytest tests/ -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: rename env vars HAT_* → MOZA_*"
```

---

### Task 3: Config + tmp paths (`~/.config/hat` → `~/.config/moza`, `$TMPDIR/hat` → `$TMPDIR/moza`)

**Files:**
- Modify: `src/moza/config.py:92-97` (`config_path()`)
- Modify: `src/moza/shell.py:35-39` (`_env_script_dir()`)
- Modify tests: `tests/test_config.py`, `tests/test_shell.py` (any assertion on
  `.config/hat` or `/hat/` tmp path)

- [ ] **Step 1: Write/adjust a failing assertion for the new config path**

In `tests/test_config.py`, ensure a test asserts the default path ends with
`.config/moza/config.json`. If an existing test asserts `.config/hat`, change it
to `moza`:

```python
def test_default_config_path(monkeypatch):
    monkeypatch.delenv("MOZA_CONFIG", raising=False)
    monkeypatch.setenv("HOME", "/home/x")
    assert str(config_path()) == "/home/x/.config/moza/config.json"
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `pytest tests/test_config.py::test_default_config_path -q`
Expected: FAIL (still `.config/hat`).

- [ ] **Step 3: Change the paths in `src/`**

- `src/moza/config.py`: `home / ".config" / "hat" / "config.json"` →
  `home / ".config" / "moza" / "config.json"`.
- `src/moza/shell.py` `_env_script_dir()`: `tmpdir / "hat"` → `tmpdir / "moza"`.

- [ ] **Step 4: Update any remaining path assertions in tests**

```bash
grep -rn '\.config/hat\|/hat"\|"hat"' tests   # inspect; fix tmp/config path asserts to moza
```

- [ ] **Step 5: Run the suite**

Run: `pytest tests/ -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: move config/tmp paths hat → moza"
```

---

### Task 4: Shell wrappers (`shell/hat.*` → `shell/moza.*`, functions, env-var refs)

**Files:**
- Move: `shell/hat.zsh` → `shell/moza.zsh`; `shell/hat.bash` → `shell/moza.bash`
- Modify: both files — functions `hat-use`/`hat-unset`/`__hat_atexit` → `moza-*`;
  `command hat` → `command moza`; `$HAT_PROFILE` → `$MOZA_PROFILE`
- Modify test: `tests/test_shell_wrappers.py` (source path + function names)

**Interfaces:**
- Produces: `shell/moza.zsh`, `shell/moza.bash` exposing `moza-use`,
  `moza-unset`.

- [ ] **Step 1: Move the wrapper files**

```bash
git mv shell/hat.zsh shell/moza.zsh
git mv shell/hat.bash shell/moza.bash
```

- [ ] **Step 2: Rewrite wrapper bodies**

```bash
for f in shell/moza.zsh shell/moza.bash; do
  perl -pi -e 's/\bhat-use\b/moza-use/g; s/\bhat-unset\b/moza-unset/g;
               s/__hat_atexit/__moza_atexit/g; s/command hat\b/command moza/g;
               s/\bHAT_PROFILE\b/MOZA_PROFILE/g;
               s{source <hat-repo>/shell/hat\.}{source <moza-repo>/shell/moza.}g' "$f"
done
grep -n 'hat' shell/moza.zsh shell/moza.bash   # expect: no output
```

- [ ] **Step 3: Update the wrapper test**

In `tests/test_shell_wrappers.py`, point the sourced path to `shell/moza.zsh` /
`shell/moza.bash` and assert `moza-use` / `moza-unset` are defined (replace any
`hat-use`/`hat.zsh` literals).

- [ ] **Step 4: Run the suite**

Run: `pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: rename shell wrappers + functions hat → moza"
```

---

### Task 5: Final code sweep — all remaining `hat` in src + tests → `moza`

This is the last code task and the one that makes the zero-legacy guard pass. It
covers everything still saying `hat` in `src/` and `tests/` (shell/ was cleared
in Task 4): backend secret naming, the keychain default prefix, all CLI
help/echo/error strings, docstrings + comments, the `HatGroup` class, and the
`hat_cfg`/`hatcfg` test identifiers. `test_shell.py` also has `/tmp/hat/` fixture
paths.

Run this task with `uv run pytest tests/ -q` (NOT plain `pytest` — a bare
interpreter is missing optional deps and shows spurious collection errors).

**Files (src):** `manifest.py`, `config.py`, `cli.py`, `backends/__init__.py`,
`backends/keychain.py`, `ephemeral.py`, `shell.py`.
**Files (tests):** `test_secret_naming.py`, `test_manifest.py`, `test_config.py`,
`test_cli.py`, `test_backends_keychain.py`, `test_backends_oci.py`,
`test_shell.py`.

**Interfaces:**
- Produces: `MANIFEST_SECRET_NAME = "moza-config-manifest"`; templates
  `moza-{profile}-{service}-{kind}`, `moza-{profile}-slack-{workspace}-token`;
  keychain default `service_prefix="moza-"`; class `MozaGroup`; test fixture
  `moza_cfg`.

- [ ] **Step 1: Compound identifiers first (order matters)**

```bash
# class HatGroup + its cls=HatGroup usage
perl -pi -e 's/\bHatGroup\b/MozaGroup/g' src/moza/cli.py
# test fixture + module alias
perl -pi -e 's/\bhat_cfg\b/moza_cfg/g; s/\bhatcfg\b/mozacfg/g' tests/*.py
```

- [ ] **Step 2: `hat-` prefixes (secret templates, keychain prefix, `hat-use`)**

Every `hat-` in src/tests is a rename target (secret templates,
`service_prefix="hat-"` default and its prompt inputs `"3\nhat-\n"`, and the
`hat-use` wrapper reference). None must stay.

```bash
perl -pi -e 's/hat-/moza-/g' \
  src/moza/manifest.py src/moza/config.py src/moza/cli.py \
  src/moza/backends/__init__.py src/moza/backends/keychain.py
grep -rl 'hat-' tests | while read -r f; do perl -pi -e 's/hat-/moza-/g' "$f"; done
grep -rn 'hat-' src tests   # expect: no output
```

- [ ] **Step 3: Standalone lowercase word `hat` (commands, docstring, comments)**

Case-sensitive `\bhat\b` — leaves English words like `that`/`what` (no boundary)
and any capitalized `Hat` (none remain) untouched. Covers `hat doctor`,
`hat init`, `hat use`, `eval "$(hat use ...)"`, `"""hat — ..."""`, `# hat's own
...`, and `/tmp/hat/` (both slashes are non-word → boundary matches).

```bash
grep -rl 'hat' src tests | while read -r f; do perl -pi -e 's/\bhat\b/moza/g' "$f"; done
```

- [ ] **Step 4: Run the suite (functional safety net)**

Run: `uv run pytest tests/ -q`
Expected: 113 passed. (If a renamed help/echo string is asserted in a test, the
substitution kept both sides in sync — a failure here means a real miss.)

- [ ] **Step 5: Zero-legacy code guard (catches compound identifiers too)**

The word-boundary grep alone misses `HatGroup`/`hat_cfg`; use a broad grep that
excludes only English words that legitimately contain the letters `hat`:

```bash
git grep -niE 'hat' -- src tests shell \
  | grep -viE '\b(that|what|whatever|somewhat|whats|thats|chat|hatch)\b'
# expect: NO output. Eyeball any remaining line — the only acceptable matches are
# English words above; anything referencing the tool is a miss to fix.
git grep -c hatchling pyproject.toml >/dev/null 2>&1 || true   # (hatchling lives in pyproject, not src)
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: sweep remaining hat → moza in src + tests"
```

---

### Task 6: Docs, plugin manifests, version unify (no sha yet)

**Files:**
- Modify: `README.md` (title, drop pun sentence, clone path `~/projects/hat` →
  `~/projects/moza`, `source .../shell/hat.zsh` → `moza.zsh`, all `hat` cmds)
- Modify: `plugins/moza/skills/moza/SKILL.md` (`name: hat` → `moza`; fallback
  `$HOME/Projects/hat/src/hat/__main__.py` → `$HOME/Projects/moza/src/moza/__main__.py`;
  `uv run --project $HOME/Projects/hat hat` → `... moza moza`; `HAT=`/`$HAT` →
  `MOZA=`/`$MOZA`; all `hat` cmds → `moza`)
- Modify: `plugins/moza/skills/moza/references/{setup-flow,usage,bootstrap,troubleshooting,schema}.md`
- Modify: `plugins/moza/skills/moza/references/schema.md`
  (`~/.config/hat/config.json` → `moza`; `hat-config-manifest` → `moza-config-manifest`)
- Modify: `plugins/moza/.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`
  (longDescription `hat` → `moza`; `version` `0.2.0` → `0.3.0`)
- Modify: `pyproject.toml` (`version` `0.1.0` → `0.3.0`)

- [ ] **Step 1: Rewrite docs (identifier-aware, exclude history)**

Edit the files above. Replace command/word `hat` → `moza`, `HAT`/`$HAT` →
`MOZA`/`$MOZA`, clone paths `Projects/hat`→`Projects/moza`,
`projects/hat`→`projects/moza`, `shell/hat.`→`shell/moza.`. Do NOT touch
`docs/superpowers/**` (history). Verify:

```bash
git grep -nwi hat -- README.md 'plugins/**/*.md' 'plugins/**/*.json'
# expect: no output
git grep -n 'Projects/hat\|projects/hat\|shell/hat\.' -- ':!docs/superpowers'
# expect: no output
```

- [ ] **Step 2: Bump versions to 0.3.0**

```bash
perl -pi -e 's/^version = "0\.1\.0"/version = "0.3.0"/' pyproject.toml
perl -pi -e 's/"version": "0\.2\.0"/"version": "0.3.0"/' \
  plugins/moza/.claude-plugin/plugin.json plugins/moza/.codex-plugin/plugin.json
```

- [ ] **Step 3: Reinstall + verify version**

```bash
uv tool install . --force
moza --version   # expect: moza, version 0.3.0
```

- [ ] **Step 4: Run the suite**

Run: `pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "docs: rename hat → moza across docs/plugins; bump to 0.3.0"
```

---

### Task 7: Migration script `scripts/migrate_from_hat.py` (run once locally)

Standalone, non-package (excluded from wheel automatically — only `src/moza` is
packaged). Run once to migrate the real config, then deleted in Task 8.

**Files:**
- Create: `scripts/migrate_from_hat.py`

**Interfaces:**
- Consumes: `moza.backends.load_backend`, `moza.config.deserialize_config`
  (primitive `.get/.list/.put` only; NOT `pull_manifest`/`push_manifest`).

- [ ] **Step 1: Write the migration script**

```python
#!/usr/bin/env python3
"""One-time hat → moza migration. Run once per machine, then delete.

Essential (always): copy ~/.config/hat/config.json → ~/.config/moza/config.json,
rewrite secret_naming templates to moza-*, re-push the config manifest under
moza-config-manifest. Existing per-secret refs are left untouched (they keep
resolving). --rekey additionally copies each hat-* secret to a moza-* name
(non-destructive, verified). --dry-run writes nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from moza.backends import load_backend
from moza.config import deserialize_config

OLD_MANIFEST = "hat-config-manifest"
NEW_MANIFEST = "moza-config-manifest"


def old_config_path() -> Path:
    return Path.home() / ".config" / "hat" / "config.json"


def new_config_path() -> Path:
    return Path.home() / ".config" / "moza" / "config.json"


def load_old_raw() -> dict:
    p = old_config_path()
    if not p.exists():
        sys.exit(f"no old config at {p}")
    return json.loads(p.read_text())


def rewrite_templates(raw: dict) -> None:
    sn = raw.get("secret_naming") or {}
    for k, v in list(sn.items()):
        if isinstance(v, str) and v.startswith("hat-"):
            sn[k] = "moza-" + v[len("hat-"):]
    raw["secret_naming"] = sn


def write_new(raw: dict, *, force: bool, dry_run: bool) -> None:
    dst = new_config_path()
    if dst.exists() and not force:
        sys.exit(f"{dst} exists; pass --force to overwrite")
    if dry_run:
        print(f"[dry-run] would write {dst}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(raw, indent=2))
    dst.chmod(0o600)
    print(f"wrote {dst}")


def migrate_manifest(raw: dict, *, dry_run: bool) -> None:
    sb = dict(raw.get("secrets_backend", {}))
    if sb.get("type") not in {"gcp_secret_manager", "oci_vault"}:
        print("local backend — no manifest to migrate")
        return
    cfg = deserialize_config(raw)
    backend = load_backend(cfg.secrets_backend)
    refs = backend.list(prefix=OLD_MANIFEST)
    if not refs:
        print("no old manifest found")
        return
    data = backend.get(refs[0])
    if dry_run:
        print(f"[dry-run] would re-push manifest as {NEW_MANIFEST}")
        return
    backend.put(NEW_MANIFEST, data)
    print(f"re-pushed manifest as {NEW_MANIFEST}")


def rekey_secrets(raw: dict, *, dry_run: bool) -> None:
    cfg = deserialize_config(raw)
    backend = load_backend(cfg.secrets_backend)
    # Walk every *_ref string in the profile blocks.
    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k.endswith("_ref") and isinstance(v, str) and "hat-" in v:
                    yield (obj, k, v)
                else:
                    yield from walk(v)
        elif isinstance(obj, list):
            for it in obj:
                yield from walk(it)
    for parent, key, ref in list(walk(raw.get("profiles", {}))):
        # OCI refs are OCIDs (name-independent) — skip.
        if ref.startswith("ocid1."):
            continue
        new_ref = ref.replace("hat-", "moza-")
        if dry_run:
            print(f"[dry-run] rekey {ref} -> {new_ref}")
            continue
        value = backend.get(ref)
        put_ref = backend.put(new_ref.split("/")[-1] if "/" in new_ref else new_ref, value)
        assert backend.get(put_ref) == value, f"verify failed for {new_ref}"
        parent[key] = put_ref
        print(f"rekeyed {ref} -> {put_ref}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rekey", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    raw = load_old_raw()
    rewrite_templates(raw)
    migrate_manifest(raw, dry_run=args.dry_run)
    if args.rekey:
        rekey_secrets(raw, dry_run=args.dry_run)
    write_new(raw, force=args.force, dry_run=args.dry_run)
    print("done" if not args.dry_run else "dry-run done")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Dry-run against the real config**

```bash
python scripts/migrate_from_hat.py --dry-run
```
Expected: prints planned actions; writes nothing; no traceback.

- [ ] **Step 3: Real run**

```bash
python scripts/migrate_from_hat.py
ls -l ~/.config/moza/config.json    # expect: exists, mode 0600
```

- [ ] **Step 4: Verify migrated state end-to-end**

```bash
moza list                    # expect: same profiles as before
moza status                  # expect: works
```
(For a cloud backend, also confirm `moza sync --dry-run` reports in-sync against
`moza-config-manifest`.)

- [ ] **Step 5: Commit the script (temporary — deleted in Task 8)**

```bash
git add scripts/migrate_from_hat.py
git commit -m "chore: add one-time hat → moza migration script (temporary)"
```

---

### Task 8: Machine cutover, delete migration script, pin marketplace sha

**Files:**
- Delete: `scripts/migrate_from_hat.py`
- Modify: `.claude-plugin/marketplace.json` (`sha`)
- Machine (outside repo content): move clone dir, edit `~/.zshrc`

- [ ] **Step 1: Move the clone dir and fix the shell source line**

```bash
cd ~
mv ~/Projects/hat ~/Projects/moza
cd ~/Projects/moza
# update ~/.zshrc: source .../Projects/hat/shell/hat.zsh -> .../Projects/moza/shell/moza.zsh
perl -pi -e 's{Projects/hat/shell/hat\.zsh}{Projects/moza/shell/moza.zsh}g' ~/.zshrc
grep -n 'Projects/hat\|shell/hat' ~/.zshrc   # expect: no output
```

> **.venv note:** the gitignored `.venv/` moves with the directory and keeps the
> old absolute paths baked into its scripts. `uv run <cmd>` detects this and
> re-syncs the environment transparently (verified: `uv run pytest` → 113 passed
> right after the `mv`). Only if you invoke the venv **directly**
> (`source .venv/bin/activate` or `.venv/bin/pytest`) do you need
> `rm -rf .venv && uv sync` first. Since every command in this plan uses
> `uv run`, no manual step is required.

- [ ] **Step 2: Verify the SKILL.md fallback path now resolves**

```bash
test -f "$HOME/Projects/moza/src/moza/__main__.py" && echo OK   # expect: OK
```

- [ ] **Step 3: Delete the migration script (last content commit)**

```bash
git rm scripts/migrate_from_hat.py
git commit -m "chore: remove one-time migration script (migration done)"
```

- [ ] **Step 4: Zero-legacy guard + build-backend integrity**

```bash
git grep -nwi hat -- ':!docs/superpowers' ':!uv.lock'
# expect: EMPTY
git grep -c hatchling pyproject.toml    # expect: >= 1
git grep -q '\[tool.hatch' pyproject.toml && echo hatch-ok   # expect: hatch-ok
```
If the first grep is non-empty, fix the missed rename and re-commit before
proceeding.

- [ ] **Step 5: Pin the marketplace sha to the current HEAD**

```bash
HEAD_SHA=$(git rev-parse HEAD)
perl -pi -e "s/\"sha\": \"[0-9a-f]{40}\"/\"sha\": \"$HEAD_SHA\"/" .claude-plugin/marketplace.json
git add .claude-plugin/marketplace.json
git commit -m "chore: sync plugin sha to rename HEAD"
```

- [ ] **Step 6: Final full verification**

```bash
uv tool install . --force
moza --version                 # expect: moza, version 0.3.0
command -v hat                 # expect: empty
uv tool list | grep hat-cli    # expect: empty
pytest tests/ -q               # expect: all pass
```

- [ ] **Step 7: Push and open the PR**

```bash
git push -u origin refactor/rename-hat-to-moza
gh pr create --fill --base main
```

---

## Self-Review

**Spec coverage:**
- §Goals 1 (package/binary) → Task 1. ✓
- §Goals 2 (env vars) → Task 2. ✓
- §Goals 3 (config/tmp paths) → Task 3. ✓
- §Goals 4 (shell wrappers) → Task 4. ✓
- §Goals 5 (secret naming) → Task 5. ✓
- §Goals 6 (docs/plugin/marketplace/versions) → Task 6 (+ sha in Task 8). ✓
- §Goals 7 (migration script, excluded+deleted) → Task 7 + Task 8 Step 3. ✓
- §Goals 8 (green suite, smoke) → every task + Task 8 Step 6. ✓
- §Clone-path references (R1) → Task 6 Step 1 (content) + Task 8 Steps 1-2 (mv). ✓
- §Landmines (hatchling) → Global Constraints + Task 8 Step 4 positive check. ✓
- §Migration F4 (primitive manifest read) → Task 7 `migrate_manifest`. ✓
- §Versioning F5 (unify 0.3.0) → Task 6 Step 2. ✓
- §N1a (uninstall hat-cli) → Task 1 Step 6. ✓
- §N1b (non-editable) → Global Constraints + Task 1 Step 6. ✓
- §R2 (sha in final commit) → Task 8 Step 5. ✓
- §Rollback → not a task (documented in spec).

**Placeholder scan:** none — all steps carry exact commands/paths. The migration
script is fully written (not a sketch) in Task 7.

**Type consistency:** import root `moza`, `MOZA_*` env vars, `moza-*` secret
names, `moza-use`/`moza-unset` used consistently across tasks. Migration script
uses `load_backend`/`deserialize_config` and backend `.get/.list/.put` only.
