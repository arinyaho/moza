# Rename `hat` → `moza` (zero-legacy, this-repo scope)

Date: 2026-07-05
Status: Approved (design, revised after review)
Sub-project 1 of 2. Sub-project 2 (`moza env sync` ambient per-project env) is
specified separately and depends on this rename landing first.

## Context

The repo currently ships under two names by design:

- Repo / Claude+Codex plugin / skill directory: **`moza`** (Korean 모자 = "hat").
- Python package, distribution, and CLI binary: **`hat`** (`src/hat/`,
  `hat-cli`, `hat = "hat.cli:main"`).

README line 7 documents the pun: *"The CLI binary is `hat`; `moza` is the
repo/plugin name (Korean 모자 = hat)."* The dual naming is a recurring source of
confusion (config lives at `~/.config/hat/` but the plugin/skill/marketplace all
say `moza`). We unify on **`moza`** everywhere.

The user is the **sole user**. We treat this as a clean **rebuild of moza**: the
tool becomes `moza`, and we do not carry `hat` compatibility.

## Scope boundary (read this first)

"Zero-legacy" is scoped to **this repository only**. Verification is a tracked-
file `git grep` (see §Testing). We consciously accept that the rename breaks
`hat` references that live **outside** this repo (e.g. another project's
`CLAUDE.md`, per-machine Claude memory files). Those are **out of scope** — no
shim, no cross-repo checklist, no `hat`→`moza` alias shipped. The user fixes
external references ad-hoc as a normal consequence of the rebuild.

This is a deliberate narrowing: the goal is honest and verifiable ("this repo
contains no `hat`"), not an unverifiable "no `hat` anywhere on the machine."

## Goals

1. Rename the Python package, distribution, and CLI binary `hat` → `moza`.
2. Rename runtime env vars `HAT_*` → `MOZA_*` and update every in-repo consumer.
3. Move config + tmp locations `~/.config/hat/` → `~/.config/moza/`,
   `$TMPDIR/hat/` → `$TMPDIR/moza/`.
4. Rename shell wrappers and their functions.
5. Rename backend secret-naming templates and the manifest secret name.
6. Update all docs, plugin manifests, marketplace metadata; unify versions.
7. Deliver a **one-time migration as an in-repo throwaway script** that is
   excluded from the built wheel and **deleted in the final pre-merge commit**
   (§Migration) — so it lives in branch history (recoverable, reviewable,
   smoke-testable) yet the merged tree and shipped package carry zero `hat`.
8. Green test suite; `moza --version` / `moza list` smoke-work.

## Non-goals

- No `moza migrate` subcommand in the package (would force legacy `hat-*` /
  `~/.config/hat/` constants to live in the shipped code forever).
- No `hat` shim / alias / compatibility entry point.
- No edits to references outside this repo (§Scope boundary).
- No behavior changes to `use` / `exec` / `token` / `sync` / `login`. Pure rename.
- Not the `moza env sync` feature (separate spec).

## Landmines (surgical rename, no blind `sed`)

The literal substring `hat` appears in tokens that MUST NOT be renamed:

- `hatchling` — the Python build backend (`pyproject.toml` `requires =
  ["hatchling"]`, `build-backend = "hatchling.build"`).
- `[tool.hatch.build.targets.wheel]` — hatchling's own config namespace.

Rename must be identifier-aware and exclude these. A `git grep -nwi hat`
(word-boundary) does **not** match `hatchling`/`hatch` — verified — so those are
never flagged by the guard; their integrity is checked separately (§Testing).

## Blast radius (inventory)

### Code (`src/hat/` → `src/moza/`)
13 modules: `__init__`, `__main__`, `cli`, `config`, `env`, `ephemeral`,
`manifest`, `oauth`, `secret_naming`, `shell`, `backends/{__init__,base,gcp,
keychain,oci}`. 34 `from hat` / `import hat` statements across `src/` + `tests/`.

### Env vars (5)
`HAT_CONFIG`, `HAT_PROFILE`, `HAT_EPHEMERAL_DIR`, `HAT_SLACK_TOKENS`,
`HAT_SLACK_DEFAULT_TOKEN` → `MOZA_*`. Defined/read in
`src/hat/{config,env,shell,cli,ephemeral}.py`. In-repo consumers:
`plugins/moza/skills/moza/SKILL.md` (+ `references/*.md`), `shell/hat.{zsh,bash}`.

### Config + tmp paths
- `config.py:92-97` `config_path()` → `~/.config/moza/config.json`;
  `HAT_CONFIG` override → `MOZA_CONFIG`.
- `shell.py:35-39` `_env_script_dir()` → `$TMPDIR/moza/`.

### Shell wrappers
`shell/hat.zsh`, `shell/hat.bash` → `shell/moza.zsh`, `shell/moza.bash`.
Functions `hat-use`, `hat-unset`, `__hat_atexit` → `moza-*`; `command hat` →
`command moza`.

### Backend secret naming (code constants only)
- `manifest.py:6` `MANIFEST_SECRET_NAME = "hat-config-manifest"` →
  `"moza-config-manifest"`.
- `config.py:159-160` + `cli.py:296-297` templates
  `hat-{profile}-{service}-{kind}` / `hat-{profile}-slack-{workspace}-token` →
  `moza-*`. Templates mint names only for **future** logins.

### Packaging
`pyproject.toml`: `name = "hat-cli"` → `"moza"`; scripts
`hat = "hat.cli:main"` → `moza = "moza.cli:main"`;
`version_option(package_name="hat-cli")` (`cli.py:96`) → `"moza"`;
`[tool.hatch.build.targets.wheel] packages = ["src/hat"]` → `["src/moza"]`.

### Docs / plugin / marketplace
`README.md` (retitle, drop the pun sentence, no migration link — see §Migration);
`SKILL.md` (`name: hat` → `moza`, all `hat`/`HAT` → `moza`/`MOZA`);
`references/{setup-flow,usage,bootstrap,troubleshooting,schema}.md`;
`plugins/moza/.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`
(longDescription); `.claude-plugin/marketplace.json` (`sha` → rename HEAD);
`schema.md` header path + reserved manifest name.

### Historical docs (leave as-is, out of guard scope)
`docs/superpowers/plans/*` and existing `specs/*` are dated historical records
that describe the tool as named at the time. Not rewritten; excluded from the
guard grep (`':!docs/superpowers'`).

### Untracked SP2 draft (out of rename scope)
`docs/ambient-project-env.issue.md` is untracked and describes the *next*
feature. `git grep` ignores untracked files, so it does not trip the guard. It
is authored as `moza` when SP2 is formally specced — not in this PR.

## Migration (in-repo throwaway script)

`scripts/migrate_from_hat.py` — a standalone one-time script.

- **Excluded from the wheel** (`packages = ["src/moza"]` only ships the package;
  `scripts/` is never packaged) and **deleted in the final pre-merge commit**.
  Net: recoverable from branch history, smoke-testable during the branch, but
  absent from the merged tree and the shipped artifact → zero-legacy holds.
- **Standalone / no version coupling.** It reads the old config with plain
  `json.load("~/.config/hat/config.json")`. For backend I/O it may load
  `moza.backends.load_backend(cfg.secrets_backend)` and use the primitive
  `.get/.list/.put` with **explicit names**, but it MUST NOT call
  `pull_manifest`/`push_manifest` — those hardcode `MANIFEST_SECRET_NAME`, which
  is now `moza-config-manifest`, whereas migration must READ the old
  `hat-config-manifest`. Old manifest is read via
  `backend.list(prefix="hat-config-manifest")` + `backend.get(...)`.

Essential path (always, non-destructive):
1. Copy `~/.config/hat/config.json` → `~/.config/moza/config.json` (0600; refuse
   to clobber an existing target without `--force`).
2. Rewrite `secret_naming` templates `hat-*` → `moza-*` in the new config
   (future logins only).
3. If backend is cloud: read old `hat-config-manifest` at primitive level and
   re-push as `moza-config-manifest`.

Existing per-secret refs (e.g. `hat-personal-github-token`) are **left
untouched** — they are stored pointers that keep resolving after the rename.

Optional `--rekey` (opt-in, non-destructive):
- For each `*_ref` resolving to a `hat-*`-named secret, copy the value to a
  `moza-*`-named secret, verify by read-back, then update the ref in the new
  config. Originals kept as backup; script prints how to delete after confirm.
- OCI refs are OCIDs (name-independent) — no-op there; skip.

`--dry-run` prints planned actions, writes nothing.

README carries **no** migration link (the script is deleted before merge; a
main-branch link would dangle). Recovery is via branch history if ever needed.

## Versioning

Unify all three artifacts to a single version, **`0.3.0`**:
- `pyproject.toml`: `0.1.0` → `0.3.0`.
- `plugins/moza/.claude-plugin/plugin.json`: `0.2.0` → `0.3.0`.
- `plugins/moza/.codex-plugin/plugin.json`: `0.2.0` → `0.3.0`.
- `.claude-plugin/marketplace.json`: plugin `sha` → rename commit HEAD.

Single version line going forward. (The `moza env sync` feature bumps to `0.4.0`
in its own PR.)

## Pre-flight

- `command -v moza` returns nothing on this machine — **no PATH collision**
  (verified). If the package is ever published, confirm the `moza` name is free
  on PyPI before `uv publish`; not required for local `uv tool install .`.

## Testing

- Update every test import `from hat` → `from moza` and every string expectation
  (`HAT_*`, `hat-*`, `~/.config/hat`, `hat-use`) to the `moza` equivalent.
- Add smoke coverage: `moza --version`, `moza list` (no config).
- Full suite green: `pytest tests/`.
- **Guard grep (final, pre-merge state — after the migration script is
  deleted):**
  - Zero-legacy check: `git grep -nwi hat -- ':!docs/superpowers' ':!uv.lock'`
    → **expected empty**. Any hit is a missed rename. (Runs on tracked files, so
    untracked drafts don't count; `docs/superpowers` history excluded.)
  - Build-backend integrity (separate positive check):
    `git grep -c hatchling pyproject.toml` → **≥ 1**, and
    `git grep -q '\[tool.hatch' pyproject.toml`. These two concerns are kept
    separate because `-w hat` never matches `hatchling`/`hatch` anyway.

## Rollout order

1. Package move + packaging → `moza --version` works.
2. Env vars → env/shell tests green.
3. Paths, shell wrappers, secret naming → full `pytest` green.
4. Docs / plugin / marketplace + version unify.
5. Write `scripts/migrate_from_hat.py`; run it locally once to migrate a real
   config; verify `moza list` / `moza use <profile>` / `moza sync` against
   migrated state.
6. Delete `scripts/migrate_from_hat.py` (final commit); guard grep clean → PR.

## Acceptance criteria

1. Guard grep empty (§Testing) at final state; `hatchling` / `[tool.hatch...]`
   intact via the positive check.
2. `moza --version` prints `0.3.0`; `moza list/status/use/token/sync` work as
   `hat` did.
3. `pytest tests/` fully green.
4. A real config migrated via the script: `~/.config/moza/config.json` (0600)
   exists, `moza list` shows the same profiles, `eval "$(moza use <p>)"`
   activates the identity, `moza sync`/`push` operate on `moza-config-manifest`.
5. Versions: pyproject / both plugins all `0.3.0`; marketplace `sha` updated.
6. `scripts/migrate_from_hat.py` absent from the merged tree; recoverable from
   branch history.

## Rollback

Pure-rename, low-risk: `git revert` the merge (or reinstall the previous
package: `uv tool install` the pre-rename commit). Old state is untouched —
`~/.config/hat/` and the `hat-*` backend secrets are left in place by migration
(non-destructive), so reverting the code restores a fully working `hat`. If
`--rekey` was run, the `moza-*` secret copies are extra (harmless) and the
`hat-*` originals still resolve.

## Risks

- **Blind replace breaks `hatchling`.** Mitigation: identifier-aware rename +
  separate positive integrity check (§Testing).
- **Migration touches live credentials** (only under `--rekey`). Mitigation:
  non-destructive copy + read-back verify + originals kept + `--dry-run`. The
  essential path never mutates existing secrets.
- **External `hat` references break** (chemcopilot, memories). **Accepted** by
  §Scope boundary — this is a rebuild, fixed ad-hoc outside this PR.
- **Orphaned old backend/local state** (`hat-config-manifest`, `~/.config/hat/`).
  Left as backup; user deletes manually after verifying `moza`.
