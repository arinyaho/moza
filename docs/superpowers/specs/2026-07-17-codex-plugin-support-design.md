# Codex plugin support (single repo, Claude + Codex)

## Goal

Make the `moza` plugin installable and functional in the **Codex CLI**, distributed from the **same repository** that already packages it for Claude Code — no separate repo, no forked skill. A user should be able to install moza in Codex the way they install any user-marketplace Codex plugin (`plugin@marketplace`), and the moza skill should trigger and run under the Codex harness.

## Background: current state

- `plugins/moza/.claude-plugin/plugin.json` — Claude plugin manifest (name/version/description/author/homepage/license). Version `0.5.0`.
- `plugins/moza/.codex-plugin/plugin.json` — Codex plugin manifest, already present. Skills-based: declares `skills: "./skills/"` plus a rich `interface` block, mirroring the official `superpowers` Codex plugin shape. Version `0.5.0`.
- `plugins/moza/skills/moza/` — the skill (SKILL.md + references/). **Portable**: pure bash-driven, resolves the `moza` binary from `PATH` (falls back to source). No Claude-specific coupling — no `Skill`/`Task`/`Agent` tool references, no `$CLAUDE_*` vars, no MCP assumptions.
- root `.claude-plugin/marketplace.json` — Claude **marketplace** listing (`name: "arinyaho"`), pointing at `plugins/moza` via a `git-subdir` source (`path: "plugins/moza"`).

**Known defect to fix in passing:** `plugins/moza/skills/moza/SKILL.md` declares `version: 0.3.0`, drifted from the `0.5.0` carried by both plugin manifests and `pyproject.toml`. Any version-sync work here must include SKILL.md, not just the three JSON files.

**Gap:** nothing advertises the moza plugin to a Codex marketplace, so it cannot be installed in Codex. The plugin manifest exists but has never been registered, installed, or run under Codex, so parity is unverified.

## How Codex consumes plugins (observed, partial)

- Codex references installed plugins as `plugin@marketplace` in `~/.codex/config.toml` (e.g. `superpowers@openai-curated`, `concord-codex@arinyaho-concord`).
- Codex maintains its **own** plugin cache at `~/.codex/plugins/cache/<marketplace>/<plugin>/<version>/`, separate from Claude's `~/.claude/plugins/cache/`. Because the registries are separate, reusing the plugin name `moza` across both harnesses cannot collide.
- A Codex plugin directory contains `.codex-plugin/plugin.json`. Two shapes seen: **skills-based** (`superpowers`, and moza today: `skills` + `interface`) and **command-based** (`concord-codex`: `commands/` + `engine/` + `bin/bundle.mjs`).
- OpenAI's curated marketplace uses a native manifest with per-plugin `policy` (`installation`, `authentication`, `products: ["CODEX"]`) and a top-level `interface.displayName`. **What a *user* marketplace must publish, and how it is registered, is not confirmed** — the precedent `concord-codex@arinyaho-concord` shows a user marketplace named `arinyaho-concord`, which suggests the marketplace name is assigned by the user at CLI-registration time (git URL → name mapping in user state), not published by the repo. This is the central unknown (Phase 0).

## Decisions

1. **Single repo, side-by-side manifests.** moza stays one repo. It already carries both `.claude-plugin/` and `.codex-plugin/` plugin manifests under `plugins/moza/`, and a Claude marketplace listing at the root. Codex support is additive; no skill fork — both harnesses load the same `plugins/moza/skills/`.
2. **Plugin name stays `moza`** in Codex (not `moza-codex`). The Codex plugin is the *same* skill, not a distinct reimplementation, so it shares the name. Separate Codex/Claude registries make this safe. (concord used a `-codex` suffix only because its Codex build is a separate command-based product.)
3. **Marketplace identity is a user-registration concern, not a repo guarantee.** The repo can only publish plugin content; the marketplace *name* (`arinyaho`, `arinyaho-moza`, etc.) is whatever the user assigns when they register the repo with the Codex CLI, exactly as `arinyaho-concord` was assigned. The README documents a *suggested* name and the resulting `moza@<name>` install target as an example, not an invariant the repo enforces.
4. **The Codex contract is resolved empirically before any file is written.** Whether a repo-published marketplace manifest is even required, its schema, and whether Codex can source a plugin from a subdir are all determined in Phase 0. Later phases are conditional on its findings.

## Plan (phased, single PR)

### Phase 0 — Verify the Codex contract *(hard gate; blocks all file writes)*

From the `codex` CLI and its docs/help, confirm:

- **Is a repo-published marketplace manifest required at all**, or is registration purely CLI-side (the user runs an `add`/register command with the repo's git URL and names the marketplace locally)? This decides whether Phase 1 authors a file or documents a command.
- If a manifest is required, its **exact schema** — Claude-format `marketplace.json` reused, vs. the native `interface` + per-plugin `policy` form.
- **Subdir source support**: can a Codex marketplace/plugin be sourced from a subdirectory (`plugins/moza`), or must the plugin sit at the repo root? If subdir is unsupported, the single-repo layout (Decision 1) needs a fallback (e.g. a root-level Codex plugin dir, or a `git-subdir`-equivalent source).
- Whether the existing skills-based `.codex-plugin/plugin.json` is loaded as-is.
- The exact user-facing command to register the marketplace and install the plugin (for the README).

**Output:** confirmed contract answering all five. May revise Decisions 1/3 and reshape Phases 1/3. No code before this passes.

### Phase 1 — Make moza registrable/installable in Codex

Driven by Phase 0:

- **If a repo manifest is required:** author it (format + location per Phase 0), listing the `moza` plugin with a Codex-valid source for `plugins/moza` (subdir or fallback per Phase 0). Leave the Claude marketplace listing untouched.
- **If registration is CLI-only:** no marketplace file; instead ensure `.codex-plugin/plugin.json` is complete for that flow.
- Either way: audit `plugins/moza/.codex-plugin/plugin.json` (`name` = `moza`, `skills` path resolves, `interface` valid) and **fix the SKILL.md version drift** so all four version-bearing files agree on `0.5.0`.

### Phase 2 — Install + parity test

- Register the marketplace / run the `add` flow and install `moza` in a real Codex session.
- Trigger the skill (e.g. "switch to my … account"); confirm it loads, resolves the `moza` binary, and runs at least one command end-to-end.
- Fix any harness gap surfaced (binary resolution, reference-file loading, prompt wording).

### Phase 3 — Tests + docs

- Add a **new** `tests/test_codex_manifest.py` (do not extend `tests/test_manifest.py`, which tests the unrelated *secrets* manifest). It locks: any Codex marketplace manifest produced in Phase 1 is valid against the confirmed schema; the `skills` path exists; and `name`/`version` stay in sync across all four version-bearing files — `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`, `pyproject.toml`, and **`skills/moza/SKILL.md`**. This test is also the first coverage of the Claude-side manifests, so it doubles as the regression guard for "Claude path unchanged".
- README: add an "Install in Codex" section next to the Claude install instructions, using the Phase 0 command and the suggested marketplace name.

## Non-goals

- No separate `moza-codex` product or command-based reimplementation.
- No changes to the skill body beyond parity fixes Phase 2 actually surfaces (the SKILL.md version bump aside).
- No publishing to OpenAI's curated marketplace.

## Success criteria

- moza installs in Codex from this repo via the Phase 0 flow (example target `moza@<marketplace>`).
- The moza skill triggers under Codex and runs a real command (identity activation) successfully.
- All four version-bearing files agree on the version, enforced by the new test; the Claude install path is unchanged and covered by that same test.
