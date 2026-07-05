# Rename `hat` → `moza` (zero-legacy)

Date: 2026-07-05
Status: Approved (design)
Sub-project 1 of 2. Sub-project 2 (`moza env sync` ambient per-project env) is
specified separately and depends on this rename landing first.

## Context

The repo currently ships under two names by design:

- Repo / Claude+Codex plugin / skill directory: **`moza`** (Korean 모자 = "hat").
- Python package, distribution, and CLI binary: **`hat`** (`src/hat/`,
  `hat-cli`, `hat = "hat.cli:main"`).

README line 7 documents the pun explicitly: *"The CLI binary is `hat`; `moza` is
the repo/plugin name (Korean 모자 = hat)."*

The dual naming is a recurring source of confusion (config lives at
`~/.config/hat/` but the plugin/skill/marketplace all say `moza`). We are
unifying on **`moza`** everywhere. After this change the codebase contains
**zero** `hat` references (one documentation link to the migration gist is the
sole exception — see §6).

The user is the **sole user** of the tool, so migration risk is low and does not
need to be shipped inside the package.

## Goals

1. Rename the Python package, distribution, and CLI binary `hat` → `moza`.
2. Rename runtime env vars `HAT_*` → `MOZA_*` and update every consumer.
3. Move config + tmp locations `~/.config/hat/` → `~/.config/moza/`,
   `$TMPDIR/hat/` → `$TMPDIR/moza/`.
4. Rename shell wrappers and their functions.
5. Rename backend secret-naming templates and the manifest secret name.
6. Update all docs, plugin manifests, marketplace metadata; bump versions.
7. Deliver a **one-time migration script as an external GitHub gist** — not
   committed to the repo — so the codebase carries no legacy `hat` constants.
8. Green test suite; `moza --version` / `moza list` smoke-work.

## Non-goals

- No `moza migrate` subcommand in the package. Migration is a throwaway gist
  (§6). Keeping migration in-code would force legacy `hat-*` / `~/.config/hat/`
  constants to live in the codebase forever — the exact cruft we are removing.
- No behavior changes to `use` / `exec` / `token` / `sync` / `login` semantics.
  This is a pure rename.
- Not the `moza env sync` ambient-env feature (separate spec).

## Landmines (surgical rename, no blind `sed`)

The literal substring `hat` appears in tokens that MUST NOT be renamed:

- `hatchling` — the Python build backend (`pyproject.toml` `requires =
  ["hatchling"]`, `build-backend = "hatchling.build"`).
- `[tool.hatch.build.targets.wheel]` — hatchling's own config namespace.

Any mechanical replace must be word/identifier-aware and must exclude these.
Verify post-rename that `hatchling` and `[tool.hatch...]` are intact.

## Blast radius (inventory)

Counts from `git grep -ci hat` (excluding `uv.lock`). Renamed by area below.

### Code (`src/hat/` → `src/moza/`)
- 13 modules under `src/hat/`: `__init__.py`, `__main__.py`, `cli.py`,
  `config.py`, `env.py`, `ephemeral.py`, `manifest.py`, `oauth.py`,
  `secret_naming.py`, `shell.py`, `backends/{__init__,base,gcp,keychain,oci}.py`.
- 34 `from hat` / `import hat` statements across `src/` and `tests/`.

### Env vars (5, runtime)
`HAT_CONFIG`, `HAT_PROFILE`, `HAT_EPHEMERAL_DIR`, `HAT_SLACK_TOKENS`,
`HAT_SLACK_DEFAULT_TOKEN` → `MOZA_*`.
- Defined/read in `src/hat/{config,env,shell,cli,ephemeral}.py`.
- Consumed externally by: `plugins/moza/skills/moza/SKILL.md` (and
  `references/*.md`), `shell/hat.{zsh,bash}`.

### Config + tmp paths
- `src/hat/config.py:92-97` `config_path()` → `~/.config/moza/config.json`;
  `HAT_CONFIG` override → `MOZA_CONFIG`.
- `src/hat/shell.py:35-39` `_env_script_dir()` → `$TMPDIR/moza/`.

### Shell wrappers
- `shell/hat.zsh`, `shell/hat.bash` → `shell/moza.zsh`, `shell/moza.bash`.
- Functions `hat-use`, `hat-unset`, `__hat_atexit` → `moza-use`, `moza-unset`,
  `__moza_atexit`. `command hat ...` → `command moza ...`.

### Backend secret naming (code constants only)
- `src/hat/manifest.py:6` `MANIFEST_SECRET_NAME = "hat-config-manifest"` →
  `"moza-config-manifest"`.
- `src/hat/config.py:159-160` + `src/hat/cli.py:296-297` default templates
  `hat-{profile}-{service}-{kind}` / `hat-{profile}-slack-{workspace}-token` →
  `moza-*`. These templates only mint names for **future** logins.

### Packaging
- `pyproject.toml`: `name = "hat-cli"` → `"moza"`; `[project.scripts]`
  `hat = "hat.cli:main"` → `moza = "moza.cli:main"`;
  `version_option(package_name="hat-cli")` in `cli.py:96` → `"moza"`;
  `[tool.hatch.build.targets.wheel] packages = ["src/hat"]` → `["src/moza"]`.

### Docs / plugin / marketplace
- `README.md` (16 hits) — retitle, drop the pun sentence, add one migration note.
- `plugins/moza/skills/moza/SKILL.md` — `name: hat` → `moza`; all `hat`
  invocations and `HAT` shell var → `moza` / `MOZA`.
- `plugins/moza/skills/moza/references/{setup-flow,usage,bootstrap,troubleshooting,schema}.md`.
- `plugins/moza/.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`
  (longDescription mentions `hat`).
- `.claude-plugin/marketplace.json` — plugin `sha` bumped to the rename HEAD.
- `plugins/moza/skills/moza/references/schema.md` — `~/.config/hat/config.json`
  header → `~/.config/moza/config.json`; `hat-config-manifest` reserved name →
  `moza-config-manifest`.

### Historical design docs (leave as-is)
`docs/superpowers/plans/*` and existing `specs/*` are dated historical records.
Do **not** rewrite them; they describe the tool as it was named at the time.
This is the one place `hat` legitimately remains, as history.

## Design per area

Each area is an independent, testable unit. Order in §Rollout.

1. **Package move.** `git mv src/hat src/moza`; rewrite imports
   (`hat` → `moza`, identifier-aware). Update `pyproject.toml` name/scripts/
   wheel packages and `version_option`. Reinstall editable (`uv sync` / `pip
   install -e .`). Gate: `moza --version` runs.

2. **Env vars.** Replace the 5 `HAT_*` identifiers in code; update
   `KNOWN_VARS` in `shell.py`, all env writes/reads, and the doc/shell
   consumers. Gate: `test_env.py`, `test_shell.py` green with `MOZA_*`.

3. **Paths.** `config_path()` and `_env_script_dir()`. Gate: config round-trip
   tests point at `~/.config/moza/`.

4. **Shell wrappers.** Rename files + functions; update `test_shell_wrappers.py`.
   README source line → `source $PWD/shell/moza.zsh`.

5. **Secret naming.** Constants + templates. Gate: `test_secret_naming.py`,
   `test_manifest.py`, `test_config.py` expectations updated to `moza-*`.

6. **Docs/plugin/marketplace + version bump.** §Versioning.

7. **Migration gist.** §Migration.

## Migration (external gist — not committed)

A standalone, self-contained Python script published as a GitHub gist. Written
during implementation, run **once** locally by the user, then discarded. The
repo never imports or references it except one README link.

What it does (essential, always):
1. Copy `~/.config/hat/config.json` → `~/.config/moza/config.json` (0600,
   refuse to clobber an existing target without `--force`).
2. In the new config, rewrite `secret_naming.default` /
   `secret_naming.slack_token` templates `hat-*` → `moza-*` (affects future
   logins only).
3. Manifest re-key: if backend is cloud (`gcp_secret_manager` / `oci_vault`),
   pull the old `hat-config-manifest`, re-push as `moza-config-manifest`.

Existing per-secret refs (e.g. `hat-personal-github-token`) are **left
untouched** — they are stored pointers that keep resolving after the rename; the
`hat-*` template is only used to mint new names. No functional need to re-key.

Optional deep re-key (`--rekey`, opt-in, non-destructive):
- For each `*_ref` in the config that resolves to a `hat-*`-named secret, copy
  the value to a `moza-*`-named secret, verify by read-back, then update the ref
  in the new config. Originals are left as backup; the script prints how to
  delete them after the user confirms.
- OCI refs are OCIDs (name-independent) — re-keying is a no-op there; skip.

`--dry-run` prints planned actions and writes nothing. The script reuses the
(post-rename) `moza` backend loaders for secret I/O, and knows the old `hat-*`
names as literals internal to itself.

README gets exactly one line: *"Migrating from the old `hat` CLI? Run the
one-time script: <gist-url>."*

## Versioning

- `pyproject.toml`: `0.1.0` → **`0.2.0`** (aligns the package with the plugins;
  rename is a breaking change to the binary name, appropriate for a pre-1.0
  minor bump).
- `plugins/moza/.claude-plugin/plugin.json` and `.codex-plugin/plugin.json`:
  `0.2.0` → **`0.3.0`**.
- `.claude-plugin/marketplace.json`: plugin `sha` → rename commit HEAD.

(The subsequent `moza env sync` feature will bump again in its own PR.)

## Testing

- Update every test import `from hat` → `from moza` and every string literal
  expectation (`HAT_*`, `hat-*`, `~/.config/hat`, `hat-use`) to the `moza`
  equivalent.
- Add smoke coverage: `moza --version`, `moza list` (no config) behave as the
  old `hat` equivalents did.
- Full suite green: `pytest tests/`.
- Post-rename guard grep: `git grep -nwi hat -- ':!docs/superpowers' ':!uv.lock'`
  returns only intended survivors (`hatchling`, `[tool.hatch...]`, the single
  README migration link). Anything else is a missed rename.

## Rollout order

1. Package move + packaging (§Design 1) → `moza --version` works.
2. Env vars (§2) → env/shell tests green.
3. Paths (§3), shell wrappers (§4), secret naming (§5) → full `pytest` green.
4. Docs / plugin / marketplace + version bump (§6).
5. Migration gist written + run locally once to verify a real config migrates
   and `moza list` / `moza use <profile>` work against migrated state.
6. Final guard grep clean → open PR.

## Acceptance criteria

1. `git grep -nwi hat` (excluding `docs/superpowers/` history and `uv.lock`)
   returns only: `hatchling`, `[tool.hatch...]`, and one README migration link.
2. `moza --version` prints the bumped version; `moza list`, `moza status`,
   `moza use <profile>`, `moza token <svc>` work as `hat` did.
3. `pytest tests/` fully green.
4. A real config migrated via the gist: `~/.config/moza/config.json` exists
   (0600), `moza list` shows the same profiles, `eval "$(moza use <p>)"`
   activates the identity, `moza sync`/`push` operate on `moza-config-manifest`.
5. `pyproject.toml` version `0.2.0`; both plugin manifests `0.3.0`; marketplace
   `sha` updated. `hatchling` / `[tool.hatch...]` intact.

## Risks

- **Blind replace breaks `hatchling`.** Mitigation: identifier-aware rename +
  post-rename verification of the build backend (§Landmines, §Testing guard).
- **Migration touches live credentials** (only with `--rekey`). Mitigation:
  non-destructive copy + read-back verification + originals kept as backup +
  `--dry-run`. Essential migration path never mutates existing secrets.
- **Orphaned old backend state** (`hat-config-manifest`, `~/.config/hat/`).
  Acceptable: left as backup; user deletes manually after verifying moza works.
