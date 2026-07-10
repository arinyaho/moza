# moza

![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Claude Code](https://img.shields.io/badge/Claude%20Code-plugin-8A2BE2)

Multi-identity credential router for Google, GitHub, and Slack — designed for developers juggling multiple accounts (personal + work) across services.

## What it does

Activate a named identity in your current shell:

```bash
eval "$(moza use personal)"
gh pr list                 # uses your personal GitHub
gcloud projects list       # uses your personal GCP
TOKEN=$(moza token google) # mint a Gmail/Cal/Drive access token on demand
```

A second shell can run `eval "$(moza use work)"` independently. No global state. No token files in your home directory.

## Architecture

- **Per-session env vars** activate `gcloud`, `gh`, etc.
- **Ephemeral files** (mode 0600, `${TMPDIR}/moza/`) hold per-session ADC + Slack tokens, cleaned on shell exit.
- **Pluggable secrets backend**: GCP Secret Manager, OCI Vault, macOS Keychain, or keyring (Linux Secret Service / Windows Credential Locker — free, no cloud, requires a desktop session).

## Install

```bash
git clone <this-repo> ~/projects/moza
cd ~/projects/moza
uv tool install .                       # or: pipx install .
echo "source $PWD/shell/moza.zsh" >> ~/.zshrc
```

## Bootstrap

```bash
moza init                               # pick a backend
moza login personal --service github
moza login personal --service google --email me@x.com --client-id <id>
moza login personal --service slack --workspace team-a
```

See `skills/moza/references/` for full docs.

## Ambient per-project env

Some env vars (e.g. `AWS_PROFILE`) are handy set automatically just by `cd`-ing into a project directory, without running `moza use`. Configure them under a profile's `project_env`, then materialize them:

```bash
moza env sync
```

This renders every profile's `project_env` scopes into `~/.config/moza/ambient.zsh` and wires `~/.zshenv` to source it (idempotent — safe to re-run). Values are non-secret only (no secrets-backend references). Coverage is **non-interactive zsh only** — `~/.zshenv` is read by every zsh invocation, but not `/bin/sh` or `bash -c`. Before writing anything, the generated script is validated with `zsh -n`; if it fails to parse, `env sync` aborts (nonzero exit) and leaves the previous ambient file and `~/.zshenv` untouched.

Example config (`match` is a bare directory glob — the directory itself and everything under it):

```json
"profiles": {
  "ccp": {
    "project_env": [
      {"match": "*/ccp/chemcopilot", "env": {"AWS_PROFILE": "ccp"}}
    ]
  }
}
```

A scope only covers a git worktree if the worktree's path is itself under the scope's glob — a worktree created in a sibling `/worktrees/` directory outside `*/ccp/chemcopilot` is NOT covered.

## As an agent skill

`moza` ships a SKILL.md that teaches AI agents (Claude Code, Hermes Agent) when and how to invoke the CLI on your behalf. The skill assumes the `moza` binary is already on `PATH` — install the CLI first (above), then add the skill:

### Claude Code

```
/plugin marketplace add arinyaho/moza
/plugin install moza@arinyaho
```

### Hermes Agent

```bash
# Install directly from GitHub
hermes skills install arinyaho/moza/skills/moza

# Or add the repo as a tap source, then install
hermes skills tap add arinyaho/moza
hermes skills install moza

# Or manually
git clone https://github.com/arinyaho/moza ~/.hermes/skills/_src/moza
ln -s ~/.hermes/skills/_src/moza/skills/moza ~/.hermes/skills/moza
```

Once installed, the agent invokes `moza` automatically when you mention identity-scoped work ("as my work account", "switch to personal", etc.).
