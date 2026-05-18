# hat config manifest sync — design

**Date:** 2026-05-18
**Status:** approved (brainstorming) — pending spec review

## Problem

`hat` secrets live in a cloud secrets backend (GCP Secret Manager / OCI Vault) and
are shared across machines. But the **profile→ref mapping plus non-secret
identifiers** (`oauth_client_id`, account emails, `gcloud_config_name`,
`default_project`, github username/host, slack workspace labels) live **only** in
the local `~/.config/hat/config.json`. SM stores only opaque secret *values* keyed
by deterministic names (`hat-{profile}-{service}-{kind}`).

Consequence: on a second machine, even though every secret already exists in SM,
the user cannot reconstruct a profile — `hat init` creates an empty config and
`hat use <profile>` fails with `profile not found`. The only workaround today is
manually copying `config.json` between machines, or re-running `hat login` (which
mints duplicate secrets and a new refresh token).

## Goal

A new machine, after `hat init` against the same backend project, recovers the
full set of profiles with **zero manual reconstruction**.

## Decisions (from brainstorming)

1. Store a **config manifest** in the cloud backend (vs. inferring from secret
   names + prompting).
2. Restore trigger: **`hat init` auto-detects** an existing manifest and offers
   import, **plus** an explicit `hat sync` command for later re-pull.
3. Upload timing: **automatic on every config save** (every `hat login`/`logout`).

## Architecture

### Manifest content & storage

- Manifest payload = exactly the JSON `_config_to_dict(cfg)` already produces
  (the serialized `config.json`). It contains **no secret values** — only refs,
  project, emails, client IDs, naming templates, and `$schema_version`. Anyone
  with read access to the backend project can already read the real secrets, so
  the manifest exposes strictly less.
- Reserved backend secret name: **`hat-config-manifest`**. This name is reserved
  and must not be used as a profile name; it does not collide with the
  `hat-{profile}-{service}-{kind}` / `hat-{profile}-slack-{workspace}-token`
  templates. Documented as reserved in `references/schema.md`.
- Scope: **cloud backends only** (`gcp_secret_manager`, `oci_vault`).
  `macos_keychain` is local-only — cross-machine sync is meaningless there, so
  manifest push/pull is skipped (no-op) for it. v1 implements and verifies the
  GCP path; OCI uses the same backend-agnostic code path
  (`backend.put` / `backend.list` / `backend.get`).

### Module boundary

New module `src/hat/manifest.py`:

- `MANIFEST_SECRET_NAME = "hat-config-manifest"`
- `is_cloud_backend(backend_cfg: BackendConfig) -> bool` — true for
  `gcp_secret_manager` / `oci_vault`.
- `push_manifest(cfg: Config, backend: SecretsBackend) -> None` — serialize
  `_config_to_dict(cfg)`, `backend.put(MANIFEST_SECRET_NAME, payload)`.
- `pull_manifest(backend: SecretsBackend) -> Config | None` — locate the
  manifest via `backend.list(prefix=MANIFEST_SECRET_NAME)`; if absent return
  `None`; else `backend.get(ref)` and parse through the existing
  `_config_from_dict` / schema-version check (reused, not duplicated).

This keeps `config.py` free of backend dependencies — the CLI layer wires
`save_config()` + `push_manifest()` together.

### Write path (automatic)

- The CLI commands that mutate config (`login`, `logout`) call
  `push_manifest(cfg, backend)` immediately after `save_config(cfg)`, only when
  `is_cloud_backend`.
- **Non-fatal on failure.** The local config and the secret were already saved
  successfully; a manifest-push failure (network/permission) must not fail
  `hat login`. Emit to stderr:
  `warning: could not sync config manifest (<reason>). Run \`hat push\` later.`
- The backend versions every put, so manifest history is retained
  (`gcloud secrets versions list hat-config-manifest`).

### Restore path & commands

**`hat init`**: after writing the fresh config and `_verify_backend`, call
`pull_manifest(backend)`. If a manifest with ≥1 profile exists:

- Interactive: prompt
  `Found an existing hat config in <project> (N profiles: a, b, ...). Import it? [Y/n]`.
  On yes, overwrite the just-written `config.json` with the manifest content.
  The backend stays the one just configured by `init` — consistent by
  construction, since the manifest was read from that same project.
- `-y` / non-interactive: auto-import (agent-friendly).
- `--no-import`: opt out even when a manifest exists.
- Echo: `Imported N profiles. Try: eval "$(hat use <first>)"`.

**`hat sync`** (new): download the manifest and reconcile the local config.
Manifest is the source of truth.

- Default: print a change summary (profiles added/removed/changed vs. local) and
  confirm before replacing local config. `-y` skips the confirm.
- `--dry-run`: print the summary only, write nothing.
- No manifest present → clear message, exit non-zero.

**`hat push`** (new, auxiliary): manually force-push the current local config to
the backend manifest. Recovery path for when an auto-push previously failed.
No-op with a notice on `macos_keychain`.

### Edge cases

- **Concurrent edits (multi-machine):** last-write-wins. Two machines editing
  around the same time → the later `save`/push wins. Recovery via backend version
  history (`gcloud secrets versions list`). v1 does **not** implement conflict
  detection (explicitly chosen: plain auto-push).
- **Security:** manifest carries no secret values (guaranteed by
  `_config_to_dict`'s output shape). Restored `config.json` keeps `chmod 600`
  (existing `save_config` behavior).
- **Schema versioning:** manifest embeds `$schema_version`. `pull_manifest`
  reuses `load_config`'s version check; an older `hat` reading a newer manifest
  fails with the existing clear "Unsupported schema_version" error.
- **Reserved name collision:** if a user already has a profile literally named
  such that its rendered secret equals `hat-config-manifest`, `hat init`/`login`
  rejects it with a clear error (validation added in `login`).

## Out of scope (separate follow-up)

- Technical input-scrubbing (a `UserPromptSubmit`/`PreToolUse` hook in the moza
  plugin to block/scrub credential patterns). Tracked as its own design; the
  current behavioral SKILL.md guardrail remains in place meanwhile.

## Testing

- `manifest.py` unit tests with a fake backend:
  - `push_manifest` puts the exact `_config_to_dict` bytes under the reserved
    name; skipped for keychain.
  - `pull_manifest` round-trips a Config; returns `None` when absent; raises on
    bad schema version.
- CLI tests (where the env permits — note the existing pytest-interpreter quirk
  that breaks `test_cli.py` collection locally; these run in CI):
  - `hat init` with a populated manifest imports profiles (interactive + `-y` +
    `--no-import`).
  - `hat sync --dry-run` reports the diff and writes nothing.
  - `hat login` triggers a manifest push; failure is non-fatal (warning only).
- Round-trip integration: build a config, `push_manifest`, wipe local,
  `pull_manifest`, assert equality.
