# `hat` — Multi-Identity Credential Router

**Date:** 2026-04-26
**Status:** Draft for review

## Summary

`hat` is a Claude Code plugin + CLI that lets a developer juggle multiple "identities" (e.g., personal, work-A, work-B), each bundling Google + GitHub + Slack credentials. Activating an identity in a shell session injects the right credentials as environment variables and ephemeral files so existing tools (`gcloud`, `gh`, `curl` to Slack API) automatically operate as that identity. Multiple Claude Code sessions can run different identities in parallel without cross-contamination.

Sensitive material (OAuth refresh tokens, PATs, Slack tokens, GCP ADC backups) is stored in a pluggable secrets backend (GCP Secret Manager, OCI Vault, or macOS Keychain). The local config file holds only references and non-sensitive metadata.

## Motivation

Today the user (and others on similar setups) maintains ~4 Google accounts, plus matching GitHub and Slack identities. Pain points:

- Re-authenticating to claude.ai-hosted Gmail/Calendar/Drive MCP servers every time a new account is needed.
- `gcloud` global active config causes cross-contamination when multiple Claude sessions run in parallel.
- No unified place to switch "who I am" — each tool needs its own ritual.
- Secrets scattered across local files, OS keychain, ad-hoc env vars.

## Non-Goals (v1)

YAGNI is enforced. The following are explicitly out of scope for v1:

- Service-specific helper commands (`hat mail search`, `hat slack post`, etc.). Existing CLIs (`gh`, `gcloud`, `bq`) and ad-hoc `curl` calls cover daily use; helpers are added in v2+ only when a pattern is repeatedly proven.
- Cross-identity fan-out / aggregation (e.g., "search all 4 mailboxes at once"). Deferred to v2+.
- Non-macOS support guarantees. v1 targets macOS (the primary user environment); Linux works in principle but is not validated.
- Web UI / GUI / TUI dashboard.
- Encrypted local file backends (age, sops, gpg). Add later if requested.
- Profile templates / cloning.
- Audit logging beyond what the underlying secret backend provides.

## Design Principles

1. **Zero hardcoding.** Plugin code contains no account names, emails, project IDs, or secret names. Every identifier is read from per-user config.
2. **Session isolation.** Activation only mutates the current shell's environment. No global state (no `gcloud config set` of active config, no rewriting `~/.config/gh/hosts.yml`).
3. **References, not values.** Local config stores secret *paths*; values live in the chosen secrets backend.
4. **Lean on existing tools.** `gcloud`, `gh`, `curl` already do the work — `hat` just routes credentials to them.
5. **Pluggable secrets backend.** A small interface; backends are added as data, not core code changes.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Claude Code plugin (multi-identity-plugin / "hat")             │
│  ┌──────────────────────┐    ┌────────────────────────────────┐ │
│  │ skills/hat/SKILL.md  │    │ bin/hat (Python entry)         │ │
│  │ — Triggers Claude to │    │ Subcommands: init, login,      │ │
│  │   use `hat` for any  │    │ logout, use, status, list,     │ │
│  │   identity work      │    │ whoami, doctor                 │ │
│  └──────────────────────┘    └────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                  │                          │
                  ▼                          ▼
       ┌──────────────────────┐   ┌──────────────────────────┐
       │ ~/.config/hat/       │   │ Secrets backend (one of) │
       │   config.json        │   │ ─ GCP Secret Manager     │
       │ (refs + metadata)    │   │ ─ OCI Vault              │
       │                      │   │ ─ macOS Keychain         │
       └──────────────────────┘   └──────────────────────────┘
                  │
                  ▼
       Per-shell env vars + ephemeral files
       ─ CLOUDSDK_ACTIVE_CONFIG_NAME
       ─ GOOGLE_APPLICATION_CREDENTIALS (ephemeral file)
       ─ CLOUDSDK_CORE_PROJECT
       ─ GH_TOKEN
       ─ HAT_PROFILE
       ─ HAT_SLACK_TOKENS (ephemeral file: workspace → token map)
```

## Configuration

### Location

`~/.config/hat/config.json` (XDG-style). Override with `HAT_CONFIG=<path>` env var. The plugin never reads `~/.tokens.json` to keep concerns separate.

### Schema

```jsonc
{
  "$schema_version": 1,

  "secrets_backend": {
    // Exactly one of:
    "type": "gcp_secret_manager",
    "project": "<gcp-project-id>"

    // OR:
    // "type": "oci_vault",
    // "vault_ocid":       "ocid1.vault.oc1...",
    // "compartment_ocid": "ocid1.compartment.oc1...",
    // "region":           "ap-chuncheon-1"

    // OR:
    // "type": "macos_keychain",
    // "service_prefix": "hat-"
  },

  "bootstrap": {
    // Backend-specific bootstrap hint. Only meaningful for cloud backends.
    "gcp_account": "primary@example.com"   // ADC account that has Secret Manager read access
    // (oci backend uses ~/.oci/config; keychain backend needs nothing)
  },

  "secret_naming": {
    // Optional. Templates used when `hat login` writes new secrets.
    // Tokens: {profile}, {service}, {kind}, [{workspace}] for slack
    "default":      "hat-{profile}-{service}-{kind}",
    "slack_token":  "hat-{profile}-slack-{workspace}-token"
  },

  "profiles": {
    "<profile-name>": {
      "google": {
        "email":                "...",
        "oauth_client_id":      "...",
        "oauth_client_secret_ref": "<secret-ref>",  // optional, can be inline
        "refresh_token_ref":    "<secret-ref>",
        "adc_ref":              "<secret-ref>",     // null if gcloud_login_required
        "gcloud_config_name":   "<profile-name>",   // typically equals profile
        "default_project":      "...",
        "gcloud_login_required": false              // true if SA/ADC blocked by org policy
      },
      "github": {
        "username":  "...",
        "host":      "github.com",                  // optional, for GHES
        "token_ref": "<secret-ref>"
      },
      "slack": [
        {
          "workspace":      "team-a",               // user-chosen label
          "team_id":        "T01ABCDEF",            // optional, helps disambiguation
          "user_token_ref": "<secret-ref>"          // xoxp- token
        }
      ]
    }
  }
}
```

All service blocks (`google`, `github`, `slack`) are optional per profile. A profile may have only `google`, or only `github`, or any combination.

### Secret Reference Format

A `*_ref` is a string the chosen backend understands:
- GCP: `projects/<p>/secrets/<n>/versions/latest`
- OCI: `ocid1.vaultsecret.oc1...`
- Keychain: `<service-name>` (combined with `service_prefix`)

The backend `get(ref)` resolves the bytes.

## CLI Surface (v1)

```
hat init                       # Interactive bootstrap wizard
hat doctor                     # Diagnose config + backend connectivity

hat list                       # List configured profiles
hat status                     # Show currently-active profile (reads $HAT_PROFILE)
hat whoami                     # Show resolved identity details for current profile

hat login <profile> [--service google|github|slack] [--workspace <name>]
                               # OAuth/PAT flow; writes secret to backend; updates config

hat logout <profile> [--service ...]   # Revokes/removes; deletes secret from backend

hat use <profile>              # Emits shell exports to stdout; user runs `eval "$(hat use ...)"`
hat unset                      # Emits shell unsets; for cleaning up

hat exec <profile> -- <cmd...> # Runs <cmd> with the profile's env (no shell mutation)
                               # e.g., `hat exec personal -- gh pr list`

hat token <service>            # Prints a fresh credential to stdout (e.g. Google access token).
                               # Routing primitive — not a service helper; used in shell pipes.
```

`hat exec` and `hat token` are credential-routing primitives, not service helpers. They are deliberately in v1: they make the routing layer usable from shell without forcing a profile switch. v1 still ships zero per-service business logic (no `mail search`, no `slack post`).

`hat use` and `hat unset` print shell snippets; they never mutate state by themselves. This keeps the tool composable and avoids "magic". A shell function wrapper (`hat-use`, `hat-unset`) is provided in `shell/` for convenience.

`hat exec` is the parallel-friendly alternative: runs a command in a subshell with the profile's env without touching the parent shell. Useful for one-off cross-identity work.

## Runtime Behavior

### `hat use <profile>` (lifecycle)

1. Load `~/.config/hat/config.json`.
2. Resolve profile entry; fail loudly if missing.
3. For each present service block:
   - **Google:**
     - Fetch `adc_ref` from backend (if not null) → write to ephemeral file at `${TMPDIR}/hat/$$-<profile>-adc.json`, mode 0600.
     - Refresh token is *not* fetched here — only when the user actually calls a Google API. Avoids unnecessary backend reads.
   - **GitHub:** Fetch `token_ref` → keep in memory; will be exported as `GH_TOKEN`.
   - **Slack:** Fetch each workspace's `user_token_ref` → write to ephemeral file `${TMPDIR}/hat/$$-<profile>-slack.json`, mode 0600, content `{ "workspace": "xoxp-...", ... }`.
4. Emit shell `export` statements to stdout:
   ```
   export HAT_PROFILE=<profile>
   export CLOUDSDK_ACTIVE_CONFIG_NAME=<gcloud_config_name>
   export CLOUDSDK_CORE_PROJECT=<default_project>
   export GOOGLE_APPLICATION_CREDENTIALS=<ephemeral path>
   export GH_TOKEN=<token>
   export HAT_SLACK_TOKENS=<ephemeral path>
   export HAT_EPHEMERAL_DIR=<dir>
   ```
5. (Caller responsibility) `eval` these in current shell.

### Cleanup

- Ephemeral files are written with `0600` and live under `${TMPDIR}/hat/`.
- A shell `trap EXIT` (installed by the convenience wrapper or by `hat init` adding to `~/.zshrc`) calls `hat unset --cleanup` on shell exit, which removes ephemeral files for this PID.
- `hat doctor --gc` sweeps stale ephemeral files (PID no longer alive).

### Why `GH_TOKEN` not `gh auth switch`

`gh` reads `GH_TOKEN` from env *and* this takes precedence over `hosts.yml`. Setting it per-shell gives perfect session isolation without mutating `~/.config/gh/hosts.yml` (which is global). One CLI, two sessions, two identities — works.

### Why `CLOUDSDK_ACTIVE_CONFIG_NAME` not `gcloud config configurations activate`

Same reasoning: `gcloud` honors this env var per-process; activating globally affects every other shell.

### Slack invocation pattern (no helper in v1)

Claude is instructed (via SKILL.md) to read `$HAT_SLACK_TOKENS` and pick the right workspace token, then `curl` Slack Web API directly. Example:

```bash
TOKEN=$(jq -r '."team-a"' "$HAT_SLACK_TOKENS")
curl -s -H "Authorization: Bearer $TOKEN" \
  'https://slack.com/api/search.messages?query=invoice'
```

If a single profile only has one Slack workspace, `HAT_SLACK_DEFAULT_TOKEN` is also exported as a convenience.

### Google API invocation pattern (no helper in v1)

Claude exchanges the refresh token for an access token using `oauth_client_id` / `oauth_client_secret` (also fetched via backend ref) and the standard refresh flow, then `curl`s the Gmail/Calendar/Drive API. Refresh tokens are not stashed in env; only fetched when needed.

For convenience, `hat token google` prints a fresh access token to stdout (callable from Bash one-liners). It is opt-in and never auto-runs.

## Secrets Backend Interface

```python
class SecretsBackend(Protocol):
    def get(self, ref: str) -> bytes: ...
    def put(self, ref: str, value: bytes) -> str:
        """Stores value; returns canonical ref (may equal input or include version)."""
    def delete(self, ref: str) -> None: ...
    def list(self, prefix: str | None = None) -> list[str]: ...
    def health_check(self) -> None:
        """Raises if backend unreachable / unauthorized."""
```

### v1 Backends

#### `gcp_secret_manager`

- Auth: Application Default Credentials. The `bootstrap.gcp_account` must already be authenticated (`gcloud auth application-default login --account=<bootstrap>`).
- Refs: `projects/<p>/secrets/<n>/versions/<v>` (defaults to `latest`).
- `put` creates secret if absent, then adds a new version.
- IAM-controlled; supports audit logging via Cloud Audit Logs.

**Bootstrap chicken-egg:** Secret Manager access requires Google ADC, which is itself an identity. Resolution: one designated "bootstrap" account's ADC is logged in locally (one-time, written to the gcloud default location `~/.config/gcloud/application_default_credentials.json`), and is used to read all other identities' material. This *bootstrap ADC* is distinct from *per-profile ADC*: per-profile ADCs are fetched on demand from the backend into ephemeral files pointed to by `GOOGLE_APPLICATION_CREDENTIALS`, never written to the gcloud default location. Documented in `bootstrap.md`.

#### `oci_vault`

- Auth: standard `~/.oci/config` profile (or env vars). API key PEM at the path referenced by the OCI config.
- Refs: secret OCID (`ocid1.vaultsecret.oc1...`).
- `put` requires `vault_ocid` and `compartment_ocid` from config; creates a new secret with the supplied name (slot fills using `secret_naming` template).
- Free tier covers typical personal use.

#### `macos_keychain`

- Auth: none (logged-in user's keychain auto-unlocks).
- Refs: opaque names like `hat-personal-google-refresh`.
- Backed by `security find-generic-password` / `add-generic-password`.
- macOS-only. No bootstrap step.

## Bootstrap Flows (`hat init`)

`hat init` is interactive; it walks the user through:

1. Pick a backend (`gcp_secret_manager` | `oci_vault` | `macos_keychain`).
2. Backend-specific setup:
   - **GCP SM:** prompt for project ID, bootstrap account email; verify `gcloud auth application-default login --account=<...>` succeeds; verify `secretmanager.versions.access` permission via a probe `get` on a non-existent secret (expect `NOT_FOUND`, not `PERMISSION_DENIED`).
   - **OCI Vault:** prompt for tenancy / vault OCID / compartment OCID / region; verify `~/.oci/config` exists and API key is loadable; do a probe `list` of vault secrets.
   - **Keychain:** prompt for `service_prefix` (default `hat-`); verify `security` CLI works.
3. Write `~/.config/hat/config.json` skeleton with no profiles.
4. Print next-step instructions: `hat login <name> --service google` etc.

`hat doctor` re-runs all probes and reports a green/yellow/red status per profile per service.

## Adding an Identity (`hat login`)

`hat login work-arinyaho --service google`:

1. Prompt for email (or use `--email` flag).
2. Run OAuth installed-app flow (`oauth_client_id` from a shared / per-user OAuth client; either pre-provided or created by user in their GCP project — *not* something `hat` provisions).
3. Receive refresh token; render secret name from `secret_naming` template; `backend.put(name, refresh_token)`.
4. (For backends that benefit) also store `oauth_client_secret` as a separate secret (`hat-<profile>-google-oauth_client_secret`).
5. Update `~/.config/hat/config.json`: add or update `profiles.<profile>.google` block with the resolved refs.
6. Optionally: trigger `gcloud auth login --account=<email>` for that profile (creates `gcloud config configurations` named after the profile and a per-config ADC); back up the ADC file to backend as `adc_ref`.

`hat login` is service-scoped (`--service google|github|slack`) so users add what they need incrementally. Profiles can be created with just `--service github` and have Google added later.

For `--service slack`, `--workspace <label>` is required, since one identity often spans multiple workspaces.

## Plugin Packaging

```
hat/                                   # repo root
├── plugin.json                         # Claude Code plugin manifest
├── README.md
├── pyproject.toml                      # uv / pip
├── shell/
│   ├── hat.zsh                         # convenience wrapper: `hat-use`, EXIT trap
│   └── hat.bash
├── bin/
│   └── hat                             # Python entry (or symlink to package main)
├── src/hat/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py                       # config load/save, schema validation
│   ├── env.py                          # build/emit env vars + ephemeral files
│   ├── oauth.py                        # google installed-app OAuth
│   └── backends/
│       ├── __init__.py                 # registry
│       ├── base.py
│       ├── gcp_secret_manager.py
│       ├── oci_vault.py
│       └── macos_keychain.py
├── plugins/                            # plugin contents
│   └── skills/
│       └── hat/
│           ├── SKILL.md                # Claude trigger doc
│           └── references/
│               ├── schema.md
│               ├── bootstrap.md
│               ├── usage.md
│               └── troubleshooting.md
├── docs/
│   ├── superpowers/specs/
│   └── architecture.md
└── tests/
```

`plugin.json` (skeleton):
```json
{
  "name": "hat",
  "version": "0.1.0",
  "description": "Multi-identity credential router for Google, GitHub, and Slack",
  "skills": ["plugins/skills/hat"]
}
```

### `SKILL.md` Triggers (sketch)

The skill's frontmatter description targets cases like:
- "switch to my <name> account/identity"
- "use my work GitHub" / "post to <workspace> Slack" / "send mail from <email>"
- Any time the user references a profile name from `hat list`

The skill's body teaches Claude to:
- Run `hat use <profile>` at start of relevant work; emit `eval "$(hat use ...)"`.
- Use `gh`, `gcloud`, `bq`, `gsutil` directly after activation — they pick up env automatically.
- For Gmail/Calendar/Drive: `hat token google | xargs -I{} curl -H 'Authorization: Bearer {}' ...`
- For Slack: read `$HAT_SLACK_TOKENS` to pick a workspace token, then `curl https://slack.com/api/...`.
- Never paste resolved tokens into the conversation; reference them via env-var shell expansion.
- For independent work in another identity, prefer `hat exec <other-profile> -- <cmd>` over switching the active profile.

## Distribution / Install

For the maintainer:
- `git push` to the repo's remote.
- Tag releases (`v0.1.0`).

For an end user (a coworker):
1. `/plugin install <git-url>` in Claude Code (or whatever the standard install path is at the time).
2. Follow the README to install Python deps (`uv tool install hat` or `pipx install hat`).
3. `hat init` — picks backend, configures.
4. `hat login <profile> --service <svc>` per service per identity.

## Security Considerations

- **No secret in transcripts.** `hat use` emits env vars containing tokens to stdout; this is then `eval`'d. Tokens *do* land in shell history if a user types `eval "$(...)"` in a way that records expansions. Mitigation: the convenience wrapper (`hat-use`) uses a function so the expansion doesn't end up in history; documented.
- **Ephemeral files mode 0600**, in `${TMPDIR}` (per-user). Cleaned on shell exit via trap; `hat doctor --gc` sweeps stale ones.
- **Refresh tokens never written to disk** outside the secrets backend.
- **GCP ADC backups** are themselves stored in the backend; only restored to ephemeral file paths, never to `~/.config/gcloud/application_default_credentials.json` (which is global).
- **Bootstrap account compromise = total compromise** of cloud-backed identities. Documented prominently. Encourage MFA + short-lived ADC.
- **macOS Keychain backend** is single-machine; secrets are protected by login session; nothing leaves the machine.
- **OAuth client_id/client_secret** are app-level credentials. Storing the secret in a vault is good practice but not catastrophic if leaked, since it doesn't grant user data access on its own.
- **Secret naming** is deterministic from profile name. If a user wants compartment isolation (e.g., separate GCP projects per identity), they can run multiple `hat init` with different `HAT_CONFIG` files.

## Open Questions

- **Multi-host support.** A single config could in principle drive multiple machines. Today the bootstrap is per-machine. Cross-machine sync via syncing `~/.config/hat/config.json` (only refs, no secrets) plus per-machine bootstrap. Documented as supported but not formally tested in v1.
- **Token rotation.** v1 has no scheduled rotation. Users rotate via `hat login` again.
- **Slack OAuth provisioning.** v1 expects `xoxp-` user tokens. Generating these requires either a Slack app the user controls or pasting from the legacy token generator. Documented; no code support beyond `hat login --service slack` accepting a pasted token.
- **GitHub fine-grained PAT vs classic.** No opinion in v1; user decides. `hat login --service github` accepts a pasted token (no OAuth flow built in).

## Implementation Phasing (preview)

Phasing details belong in the implementation plan; sketched here for context:

1. Config + backend interface + `gcp_secret_manager` backend + `hat init`/`status`/`list`.
2. `macos_keychain` backend.
3. `oci_vault` backend.
4. `hat login --service github` + `hat use` env emission for GitHub.
5. `hat login --service google` + `hat use` env emission for Google + `hat token google`.
6. `hat login --service slack` + `hat use` env emission for Slack.
7. `hat exec`, `hat doctor`, shell convenience wrappers.
8. SKILL.md authoring + plugin manifest + install docs.

## References

- daramg `~/.code-assistant.json` — inspiration for "refs in local config, values in cloud secret manager" pattern.
- Google OAuth installed-app flow — https://developers.google.com/identity/protocols/oauth2/native-app
- GCP Secret Manager IAM model.
- Slack Web API token types (xoxp / xoxb / xapp).
