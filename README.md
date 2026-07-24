# mien

![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Claude Code](https://img.shields.io/badge/Claude%20Code-plugin-8A2BE2)

Multi-identity credential router for Google, GitHub, and Slack — designed for developers juggling multiple accounts (personal + work) across services.

## What it does

Activate a named identity in your current shell:

```bash
eval "$(mien use --owner-pid $$ personal)"   # or: mien-use personal (the wrapper passes $$ for you)
gh pr list                 # uses your personal GitHub
gcloud projects list       # uses your personal GCP
TOKEN=$(mien token google) # mint a Gmail/Cal/Drive access token on demand
```

A second shell can run `mien-use work` (or `eval "$(mien use --owner-pid $$ work)"`) independently — activation touches only that shell. Tokens live in a secrets backend rather than in a dotfile.

## Architecture

- **Per-session env vars** activate `gcloud`, `gh`, etc.
- **Ephemeral files** (mode 0600, `${TMPDIR}/mien/`) hold per-session ADC, SSH key and Slack tokens. `mien exec` and `mien run` delete theirs when the child exits; the ones `mien use` leaves for your shell are swept on a best-effort basis — see [SECURITY.md](SECURITY.md#lifetime-and-cleanup).
- **Pluggable secrets backend**: GCP Secret Manager, OCI Vault, macOS Keychain, or keyring (Linux Secret Service / Windows Credential Locker — free, no cloud, requires a desktop session).

[SECURITY.md](SECURITY.md) describes what is stored where, who can read it, and what `mien` deliberately does not protect — including that it does **not** hide credentials from an AI agent it hands them to.

## Install

### CLI

```bash
uv tool install git+https://github.com/arinyaho/mien    # or: pipx install git+https://github.com/arinyaho/mien
echo 'eval "$(mien shell-init)"' >> ~/.zshrc            # adds the mien-use / mien-unset wrappers
```

No checkout needed — both lines install from the repo directly. `mien shell-init` prints the shell wrappers; `eval`-ing it defines `mien-use` and `mien-unset` and wires the exit-trap cleanup. Use `--shell bash` (or add to `~/.bashrc`) for bash.

To hack on it, clone and install from the working tree instead:

```bash
git clone https://github.com/arinyaho/mien ~/projects/mien
cd ~/projects/mien && uv tool install --editable .
```

### As an agent skill

`mien` ships a SKILL.md that teaches AI agents (Claude Code, Codex, Hermes Agent) when and how to invoke the CLI on your behalf. The skill assumes the `mien` binary is already on `PATH` — install the CLI first (above), then add the skill:

**Claude Code:**

```bash
/plugin marketplace add arinyaho/mien
/plugin install mien@arinyaho
```

**Codex:**

```bash
codex plugin marketplace add arinyaho/mien --ref main   # register the marketplace
codex plugin add mien@arinyaho                           # install the plugin
```

Update the Codex plugin: `codex plugin marketplace upgrade arinyaho` then re-run `codex plugin add mien@arinyaho`. Uninstall: `codex plugin remove mien@arinyaho` (and, optionally, `codex plugin marketplace remove arinyaho`).

**Hermes Agent:**

```bash
# Install directly from GitHub
hermes skills install arinyaho/mien/skills/mien

# Or add the repo as a tap source, then install
hermes skills tap add arinyaho/mien
hermes skills install mien

# Or manually
git clone https://github.com/arinyaho/mien ~/.hermes/skills/_src/mien
ln -s ~/.hermes/skills/_src/mien/skills/mien ~/.hermes/skills/mien
```

Once installed, the agent invokes `mien` automatically when you mention identity-scoped work — e.g. "as my work account", "switch to personal".

## Bootstrap

```bash
mien init                               # pick a backend
mien login personal --service github
mien login personal --service google --email me@x.com --client-id <id>
mien login personal --service slack --workspace team-a
```

See `skills/mien/references/` for full docs.

## Project-pinned identity

A profile can claim directories, so work in those directories runs as the right identity without anyone naming it:

```json
"profiles": {
  "work":     { "default_for": ["*/Projects/acme*"] },
  "personal": { "default_for": ["*/Projects/mien", "*/Projects/sayu"] }
}
```

```bash
mien which                       # → work
mien run -- gh pr list           # runs as whichever profile claims this directory
```

A scope covers the directory itself and everything under it. Sibling directories that merely share a prefix are not covered — `*/Projects/acme` does not capture `acme-fork`. When two profiles claim a directory, the longer scope wins; when they are equally specific, `mien` refuses rather than guessing, since picking one would misroute credentials silently.

`~` and `$VAR` are expanded, so `~/Projects/acme` and `$HOME/Projects/acme` both work. A variable that is not set — or is set to the empty string — is left as written, which matches nothing; the same goes for `~` under an empty `HOME`. The generated `project_env` shell would instead drop it and widen the scope, and quietly claiming more directories than intended is the wrong way to fail here.

If a profile is already active in the shell (`MIEN_PROFILE`), it wins — an explicit `mien use` is a deliberate act and a directory default should not undo it. `mien which` prints a warning to stderr when the two disagree.

Scopes live in your own config. Nothing in a checked-out repository can contribute a scope, name a profile, or reach an identity you have not already granted to some directory.

A cloned directory is still matched like any other, though: `*` spans `/`, the same as in the shell patterns these scopes compile to, so a scope of `*/work/*` claims a `work` directory at any depth — including one inside a repository you just cloned. `git clone` names the target after the remote by default, so this is reachable by accident, and it turns a directory that would otherwise fail closed into one that runs under a real identity. Anchor scopes at `~` or a literal root rather than a leading `*` if that matters to you.

Because resolution reads the filesystem on every call and keeps no state, it works the same in a long-lived terminal and in an AI agent that starts a fresh shell for every command.

## Who am I here — in the status line

The identity you would act as is worth seeing *before* you act, not after a personal commit has landed in a work repository. `mien statusline` renders a one-line segment for a [Claude Code status line](https://docs.claude.com/en/docs/claude-code/statusline) that keeps the answer in view and turns red when the active identity is wrong for the directory:

```json
// .claude/settings.json
{ "statusLine": { "type": "command", "command": "mien statusline" } }
```

```
🟢 mien:work                       # this place's identity agrees with what's active
🔴 mien:personal ✗ repo is work's  # personal is active, but this repo belongs to work
🔴 mien:personal ✗ dir wants work  # ...or a directory scope claims work
🔴 author:personal ✗ repo is work's # nothing active, but git user.email would commit as personal
🟡 mien:— no profile here          # nothing set, and nothing claims this place
```

The red case is the one that matters: an agent session that inherited `personal` from the shell it launched in, sitting in a `work` repository, is exactly how the wrong identity commits.

The `author:` case closes that even when you activate nothing: it compares the git `user.email` a commit here would carry against the emails your profiles already declare (their Google and Atlassian accounts, and the GitHub no-reply address). If that email positively belongs to a *different* profile than the repository's owner, it warns — including the subtle case where the right profile is active but `user.email` is still stale. It stays quiet on an email it does not recognize, so a legitimate alternate address raises no false alarm.

It figures out whose place this is from two signals — the repository's `origin` owner (`owns_remotes`) and directory scopes (`default_for`) — so it works whether or not you organize by directory. If you keep repositories side by side with no per-employer folder, the remote owner is what makes it sharp:

```json
"profiles": {
  "work":     { "owns_remotes": ["github.com/acme-*/*"] },
  "personal": { "owns_remotes": ["github.com/me/*", "github.com/me-labs/*"] }
}
```

A profile can own several remote patterns — a personal account and the organizations it also manages. The remote owner is **advisory only**: it drives the status line's display and warning, never `run`/`exec` (which *act*), because a checked-out repository controls its own remote and must not be able to choose the identity that acts. It reads config names and scopes only, never a token, so it is safe to run at status-line frequency, and it prints nothing when `mien` is not configured.

## Ambient per-project env

Some env vars (e.g. `AWS_PROFILE`) are handy set automatically just by `cd`-ing into a project directory, without running `mien use`. Configure them under a profile's `project_env`, then materialize them:

```bash
mien env sync
```

This renders every profile's `project_env` scopes into `~/.config/mien/ambient.zsh` and wires `~/.zshenv` to source it (idempotent — safe to re-run). Values are non-secret only (no secrets-backend references). Coverage is **non-interactive zsh only** — `~/.zshenv` is read by every zsh invocation, but not `/bin/sh` or `bash -c`. Before writing anything, the generated script is validated with `zsh -n`; if it fails to parse, `env sync` aborts (nonzero exit) and leaves the previous ambient file and `~/.zshenv` untouched.

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

### Variables in a `match` scope

The generated script is sourced from `~/.zshenv`, and zsh reads `~/.zshenv` **before** `~/.zshrc` and `~/.zprofile`. A variable you export from your own dotfiles is therefore unset at the moment the scope is matched, and zsh expands it to nothing: `{"match": "$WORK_ROOT/*"}` becomes the pattern `/*`, which matches every absolute path, so that scope's env — `AWS_PROFILE` and all — is applied in every directory. A reference in the middle of a path is not broader but wrong in a different way: `$WORK_ROOT/acme` becomes `/acme`, disjoint from the tree you meant.

Only parameters that already have a value that early are safe: the ones zsh sets itself (`$HOME`, `$PWD`, `$PATH`, `$UID`, …) and the ones the login process puts in the environment zsh inherits (`$USER`, `$SHELL`, …). `~` is safe too — tilde expansion consults the password database and needs no variable. `$TMPDIR` is deliberately *not* on that safe list: macOS launchd sets it, but stock sshd and a default Linux PAM do not, so `env sync` warns about a `$TMPDIR`-rooted scope rather than assume one OS. For anything else, write a literal path. `mien env sync` warns on stderr, naming the profile and the scope, and still writes the file, so a config that works today keeps working.

A scope only covers a git worktree if the worktree's path is itself under the scope's glob — a worktree created in a sibling `/worktrees/` directory outside `*/work/arinyaho` is NOT covered.
