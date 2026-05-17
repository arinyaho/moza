# hat

Multi-identity credential router for Google, GitHub, and Slack — designed for developers juggling multiple accounts (personal + work) across services.

## What it does

Activate a named identity in your current shell:

```bash
eval "$(hat use personal)"
gh pr list                # uses your personal GitHub
gcloud projects list      # uses your personal GCP
TOKEN=$(hat token google) # mint a Gmail/Cal/Drive access token on demand
```

A second shell can run `eval "$(hat use work)"` independently. No global state. No token files in your home directory.

## Architecture

- **Per-session env vars** activate `gcloud`, `gh`, etc.
- **Ephemeral files** (mode 0600, `${TMPDIR}/hat/`) hold per-session ADC + Slack tokens, cleaned on shell exit.
- **Pluggable secrets backend**: GCP Secret Manager, OCI Vault, or macOS Keychain.

## Install

```bash
git clone <this-repo> ~/projects/hat
cd ~/projects/hat
uv tool install .                      # or: pipx install .
echo "source $PWD/shell/hat.zsh" >> ~/.zshrc
```

## Bootstrap

```bash
hat init                               # pick a backend
hat login personal --service github
hat login personal --service google --email me@x.com --client-id <id>
hat login personal --service slack --workspace team-a
```

See `skills/hat/references/` for full docs.

## As an agent skill

`hat` ships a SKILL.md that teaches AI agents (Claude Code, Hermes Agent) when and how to invoke the CLI on your behalf. The skill assumes the `hat` binary is already on `PATH` — install the CLI first (above), then add the skill:

### Claude Code

```
/plugin marketplace add arinyaho/hat
/plugin install hat@arinyaho/hat
```

### Hermes Agent

```bash
# Install directly from GitHub
hermes skills install arinyaho/hat/skills/hat

# Or add the repo as a tap source, then install
hermes skills tap add arinyaho/hat
hermes skills install hat

# Or manually
git clone https://github.com/arinyaho/hat ~/.hermes/skills/_src/hat
ln -s ~/.hermes/skills/_src/hat/skills/hat ~/.hermes/skills/hat
```

Once installed, the agent invokes `hat` automatically when you mention identity-scoped work ("as my work account", "switch to personal", etc.).
