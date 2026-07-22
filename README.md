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

### CLI

```bash
git clone <this-repo> ~/projects/moza
cd ~/projects/moza
uv tool install .                       # or: pipx install .
echo "source $PWD/shell/moza.zsh" >> ~/.zshrc
```

### As an agent skill

`moza` ships a SKILL.md that teaches AI agents (Claude Code, Codex, Hermes Agent) when and how to invoke the CLI on your behalf. The skill assumes the `moza` binary is already on `PATH` — install the CLI first (above), then add the skill:

**Claude Code:**

```bash
/plugin marketplace add arinyaho/moza
/plugin install moza@arinyaho
```

**Codex:**

```bash
codex plugin marketplace add arinyaho/moza --ref main   # register the marketplace
codex plugin add moza@arinyaho                           # install the plugin
```

Update the Codex plugin: `codex plugin marketplace upgrade arinyaho` then re-run `codex plugin add moza@arinyaho`. Uninstall: `codex plugin remove moza@arinyaho` (and, optionally, `codex plugin marketplace remove arinyaho`).

**Hermes Agent:**

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

Once installed, the agent invokes `moza` automatically when you mention identity-scoped work — e.g. "as my work account", "switch to personal".

## Bootstrap

```bash
moza init                               # pick a backend
moza login personal --service github
moza login personal --service google --email me@x.com --client-id <id>
moza login personal --service slack --workspace team-a
```

See `skills/moza/references/` for full docs.

## Project-pinned identity

A profile can claim directories, so work in those directories runs as the right identity without anyone naming it:

```json
"profiles": {
  "work":     { "default_for": ["*/Projects/acme*"] },
  "personal": { "default_for": ["*/Projects/moza", "*/Projects/sayu"] }
}
```

```bash
moza which                       # → work
moza run -- gh pr list           # runs as whichever profile claims this directory
```

A scope covers the directory itself and everything under it. Sibling directories that merely share a prefix are not covered — `*/Projects/acme` does not capture `acme-fork`. When two profiles claim a directory, the longer scope wins; when they are equally specific, `moza` refuses rather than guessing, since picking one would misroute credentials silently.

`~` and `$VAR` are expanded, so `~/Projects/acme` and `$HOME/Projects/acme` both work. A variable that is not set — or is set to the empty string — is left as written, which matches nothing; the same goes for `~` under an empty `HOME`. The generated `project_env` shell would instead drop it and widen the scope, and quietly claiming more directories than intended is the wrong way to fail here.

If a profile is already active in the shell (`MOZA_PROFILE`), it wins — an explicit `moza use` is a deliberate act and a directory default should not undo it. `moza which` prints a warning to stderr when the two disagree.

Scopes live in your own config, never in a checked-out repository, so cloning a repository can never change which identity acts on your machine.

Because resolution reads the filesystem on every call and keeps no state, it works the same in a long-lived terminal and in an AI agent that starts a fresh shell for every command.

## Ambient per-project env

Some env vars (e.g. `AWS_PROFILE`) are handy set automatically just by `cd`-ing into a project directory, without running `moza use`. Configure them under a profile's `project_env`, then materialize them:

```bash
moza env sync
```

This renders every profile's `project_env` scopes into `~/.config/moza/ambient.zsh` and wires `~/.zshenv` to source it (idempotent — safe to re-run). Values are non-secret only (no secrets-backend references). Coverage is **non-interactive zsh only** — `~/.zshenv` is read by every zsh invocation, but not `/bin/sh` or `bash -c`. Before writing anything, the generated script is validated with `zsh -n`; if it fails to parse, `env sync` aborts (nonzero exit) and leaves the previous ambient file and `~/.zshenv` untouched.

Example config (`match` is a bare directory glob — the directory itself and everything under it):

```json
"profiles": {
  "work": {
    "project_env": [
      {"match": "*/work/arinyaho", "env": {"AWS_PROFILE": "work"}}
    ]
  }
}
```

A scope only covers a git worktree if the worktree's path is itself under the scope's glob — a worktree created in a sibling `/worktrees/` directory outside `*/work/arinyaho` is NOT covered.
