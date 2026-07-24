---
name: mien
description: Use when the user wants to act as a specific identity/profile across Google (Gmail/Calendar/Drive/GCP), GitHub, Slack, Atlassian, Notion, AWS, or OCI — e.g., "as my work account", "switch to <name>", "post in <workspace>", "send mail from <email>". Activates per-shell credentials for `gh`, `gcloud`, `bq`, `aws`, `oci`, and `curl` calls without polluting other agent sessions.
version: 0.5.0
author: arinyaho
license: MIT
compatibility: works best with `mien` on PATH; falls back to source if available
metadata:
  hermes:
    tags: [identity, credentials, multi-account, gcp, github, slack, atlassian, notion, aws, oci]
    related_skills: []
---

# mien — Multi-identity credential router

The user maintains multiple identities, each bundling a Google account (Gmail/Calendar/Drive + GCP) and optionally a GitHub account, one or more Slack workspaces, an Atlassian account (Jira/Confluence), a Notion integration token, AWS credentials, and/or an OCI profile. Use `mien` to activate the right identity in this shell session.

## When to use

Trigger any time:
- The user names a profile (`personal`, `work-foo`, etc.) and asks for an action that needs auth.
- The user asks "as <email>" / "from <email>" / "with my <something> account".
- A multi-account task (one profile per agent session) — `mien` is what isolates them.
- The user wants to call Atlassian APIs (Jira, Confluence) under a specific identity.
- The user wants to call the Notion API under a specific identity.
- The user wants to run AWS CLI / SDK calls under a specific identity.
- The user wants to run OCI CLI calls under a specific identity.

If the user has not configured `mien`, **don't just punt** — drive the conversational setup flow described in `references/setup-flow.md`. Detect state with `mien doctor` (or `mien list` if doctor fails), then guide the user step by step.

## Invoking mien

Before running any `mien` command, resolve the binary:

```bash
# Prefer installed binary; fall back to source repo
if command -v mien &>/dev/null; then
  MIEN="mien"
elif [ -f "$HOME/Projects/mien/src/mien/__main__.py" ]; then
  MIEN="uv run --project $HOME/Projects/mien mien"
else
  echo "mien not found — install it (no checkout needed): uv tool install git+https://github.com/arinyaho/mien"
  exit 1
fi
```

Use `$MIEN` instead of `mien` in all subsequent commands.

## Core commands

```
$MIEN list                          # see profiles
$MIEN status                        # what is active in *this* shell
$MIEN whoami [<profile>]            # the whole bundled identity as a card; --json for machine form; --live to verify
$MIEN use <profile>                 # prints a `source …; rm …` loader; eval to activate (same call only)
$MIEN exec <profile> -- <cmd...>    # run cmd with the profile's env — prefer this
$MIEN which                         # profile claimed by the current directory
$MIEN claim <profile>               # bind THIS workspace to a profile via a local .mien (writes, approves, git-ignores)
$MIEN allow                         # approve an existing .mien so it can drive identity here
$MIEN run -- <cmd...>               # run cmd as that profile
$MIEN token google --profile <p>    # mint a fresh google access token (for curl)
$MIEN statusline                    # one-line identity segment for a Claude Code status line
$MIEN prompt                        # same segment for a shell prompt (zsh RPROMPT / bash PS1)
$MIEN guard                         # exit non-zero if the identity is confidently wrong for this repo
```

**Project-local declaration (`.mien`).** The simplest way to bind a workspace to a profile is a `.mien` file naming it — `mien claim <profile>` writes it, approves it, and adds it to the global git ignore in one step. `mien run`/`which` and the status line then act as that profile for the whole tree, with no central scope. Security: a `.mien` is a checked-out file, so it does **not** drive the acting identity until the user approves it (`mien allow`) — a cloned repo's `.mien` is inert, and an edited one must be re-approved. If a directory declares an unapproved `.mien`, `mien which`/`run` fail loud (they don't silently route); tell the user to run `mien allow`. Precedence: `MIEN_PROFILE` → approved `.mien` → central `default_for`/`owns_remotes`.

**Ambient identity across harnesses.** Three surfaces show/enforce "who am I here", with different reach:
- `mien statusline` — the **Claude Code** status line (wired via `.claude/settings.json` `statusLine`). Claude Code-specific; other harnesses (e.g. Codex) expose no equivalent status-line hook.
- `mien prompt` — a **shell prompt** segment (`RPROMPT='$(mien prompt)'`), so the same indicator shows in any ordinary terminal, independent of harness.
- `mien guard` — the **enforcement**, and it is harness-agnostic: as a git pre-commit hook it blocks a mis-authored commit in *any* session (Claude Code, Codex, a plain shell), and it is the strongest of the three guarantees. Prefer it when the goal is prevention rather than display.

**Refusal gate.** `mien guard` is the acting counterpart of the status line: it exits non-zero (refusing the action) only on a confident mismatch — the active `MIEN_PROFILE`, or the git author a commit would carry, positively belongs to a different profile than the repo's `origin` owner. If the user wants mis-authored commits blocked, wire it as a pre-commit hook: `echo 'exec mien guard' > .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit` (or a global `core.hooksPath`). It fails open (allows) on any uncertainty or error, and every refusal is overridable (`MIEN_GUARD=off`, `--force`, `git commit --no-verify`). Blocking with repo signals is safe (a crafted remote at worst causes a false refusal you override); the acting path still never trusts the repo.

**Status line.** If the user wants the active identity always visible (e.g. "show which profile I'm on"), wire `mien statusline` into their `.claude/settings.json`: `"statusLine": { "type": "command", "command": "mien statusline" }`. It reads Claude Code's session JSON on stdin and compares `MIEN_PROFILE` against whose place this is — the repository's `origin` owner (`owns_remotes`) or a directory `default_for` scope — printing green when they agree and red (`✗ repo is <other>'s` / `✗ dir wants <other>`) when the active identity is wrong here. It also cross-checks the repo's git `user.email` against the emails profiles declare and warns (`author:<other> ✗ …`) when a commit here would be authored as a *different* profile than the owner — catching a mis-commit even with nothing activated, while staying quiet on an unrecognized email. The remote owner and the author check are advisory-only (display/warning, never used to pick an acting identity, since a checked-out repo controls both its remote and its `user.email`). Secret-free and silent when `mien` is unconfigured.

## Activation pattern

**Your shell state does not survive between tool calls.** Claude Code, Codex, and most
agent harnesses start a fresh shell for every command invocation, so environment
variables set by `eval "$($MIEN use ...)"` are gone by your next call.

Nothing errors when this happens. The next command simply runs as whatever identity the
ambient shell already had. For a credential router that is the worst possible failure
mode: you believe you are acting as `work-foo`, and you are acting as something else.

Three patterns are safe. Use one of them; never rely on an `eval` from an earlier call.

**1. `$MIEN run` — preferred when the project pins its own identity.**

If the user has given profiles `default_for` scopes, the directory already knows who to
be, and you never have to name a profile:

```bash
$MIEN which                       # confirm, if the identity matters
$MIEN run -- gh pr list
$MIEN run -- gcloud projects list
```

**`run` is not purely directory-driven.** If `MIEN_PROFILE` is already set, it wins over the
directory — and it very often is: a session launched from a terminal where the user ran
`mien-use work` inherits it into every one of your commands, so `run` acts as `work` even in
a directory pinned to something else. `$MIEN which` reports the conflict, but only as a
warning on stderr, and it still exits 0. So when the identity matters, do not just check the
exit status — read what `which` printed, or name the profile with `exec` and leave nothing
to inherit.

**2. `$MIEN exec` — when you must name the profile.**

```bash
$MIEN exec work-foo -- gh pr list
$MIEN exec work-foo -- aws sts get-caller-identity
```

Both carry the identity per invocation, so there is no earlier `eval` left to expire. Both
layer the profile *over* the ambient env rather than replacing it, though: for a service the
profile does not define — a profile with no `aws` block still inherits an ambient
`AWS_ACCESS_KEY_ID` — the ambient credential still wins, so confirm with the service's own
identity check below.

**3. Single-call `eval` — for a sequence that must share one shell.**

Every line below must be in **one** command invocation:

```bash
eval "$($MIEN use work-foo)"
gh pr list                        # uses GH_TOKEN
gcloud projects list              # uses CLOUDSDK_ACTIVE_CONFIG_NAME
bq ls -p                          # ditto
```

Splitting those lines across two tool calls is the bug described above.

**Confirm the identity when the action is destructive or the profile matters.** `$MIEN
whoami --live <profile>` asks GitHub, AWS, and Google who the profile actually
authenticates as, compares it to the config, and exits non-zero on any mismatch or dead
credential — so it gates the action when chained before it:

```bash
$MIEN whoami --live work-foo && $MIEN exec work-foo -- gh pr merge 123
```

Its exit code is the gate; a wrong live identity or a revoked token stops the `&&`. Caveats
worth knowing: a provider that could not be reached is reported but does not fail the check
(could-not-check is not the same as wrong); AWS is reported, not verified, since a profile
name is not an ARN there is nothing to compare; and slack/atlassian/notion/oci are not
probed yet, so `--live` names them as unchecked rather than pretending it verified them. For
a single service you can also inline the comparison, since a bare `gh api user` succeeds
under *any* valid token and exit status alone gates nothing:

```bash
[ "$($MIEN run -- gh api user -q .login)" = "expected-login" ] \
  && $MIEN run -- gh pr merge 123
```

For Gmail/Calendar/Drive (no helper in v1 — use curl). Pass `--profile` explicitly so the
call does not depend on ambient shell state:

```bash
TOKEN=$($MIEN token google --profile work-foo)
curl -s -H "Authorization: Bearer $TOKEN" \
  'https://gmail.googleapis.com/gmail/v1/users/me/messages?q=from:foo'
```

For Slack (multi-workspace per profile):

```bash
eval "$($MIEN use work-foo)"      # same call: brings in MIEN_SLACK_TOKENS
TOKEN=$(jq -r '."team-a"' "$MIEN_SLACK_TOKENS")
curl -s -H "Authorization: Bearer $TOKEN" \
  'https://slack.com/api/conversations.list'
```

If the profile has only one workspace, `$MIEN_SLACK_DEFAULT_TOKEN` is also exported.

For Atlassian (Jira/Confluence):

```bash
TOKEN=$($MIEN token atlassian --profile work-foo)
eval "$($MIEN use work-foo)"      # same call: brings in ATLASSIAN_EMAIL / _BASE_URL
curl -s -u "$ATLASSIAN_EMAIL:$TOKEN" \
  "$ATLASSIAN_BASE_URL/rest/api/3/issue/PROJ-123"
```

`ATLASSIAN_EMAIL`, `ATLASSIAN_API_TOKEN`, and `ATLASSIAN_BASE_URL` are also exported directly by `mien use`.

For Notion:

```bash
TOKEN=$($MIEN token notion --profile work-foo)
curl -s -H "Authorization: Bearer $TOKEN" -H "Notion-Version: 2022-06-28" \
  https://api.notion.com/v1/users/me
```

`NOTION_TOKEN` is also exported directly by `mien use`.

For AWS:

```bash
$MIEN exec work-foo -- aws s3 ls                     # uses AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY or AWS_PROFILE
$MIEN exec work-foo -- aws sts get-caller-identity   # verify active identity
```

`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_PROFILE`, and `AWS_DEFAULT_REGION` are exported by `mien use`.

For OCI:

```bash
$MIEN exec work-foo -- oci iam user get --user-id <ocid>   # uses OCI_CLI_PROFILE / OCI_CLI_CONFIG_FILE
```

`OCI_CLI_PROFILE` and `OCI_CLI_CONFIG_FILE` are exported by `mien use`.

## Important rules

- **Never assume a profile is still active.** Environment set by an earlier tool call is gone (see *Activation pattern*). Every invocation must carry its own identity — via `mien exec`, an `eval` in that same invocation, or `--profile`. A command that "worked a moment ago" is not evidence the profile is still set.
- **Never paste resolved tokens into the conversation.** Use shell expansion (`$GH_TOKEN`, `$($MIEN token google --profile <p>)`) so the token resolves at execution time and never appears in tool-call arguments.
- **Never run `mien use` bare** — always `eval` it (or use the `mien-use` wrapper). As an extra safety net `mien use` writes exports to a 0600 ephemeral file and only prints a `source …; rm …` one-liner, so a missed `eval` no longer leaks tokens to stdout. On a real TTY `mien use` refuses outright (use `mien-use` or `eval`).
- **In a persistent human shell, pass an owner pid** — use the `mien-use` wrapper (it passes `$$`), or `eval "$(mien use --owner-pid $$ <profile>)"`. Without it the ephemeral files are keyed to mien's already-exited process, and a stray `mien doctor --gc` then deletes credentials the shell is still using. This does **not** apply to the single-call agent form above: that shell is short-lived and dies with the invocation, so keying the files to it or to mien amounts to the same thing, and they are meant to be reclaimed.
- **Never run `mien login` yourself to enter a secret.** The agent's shell is non-interactive, so you would have to put the secret in the command — which lands in the session transcript and shell history. Instead:
  - Tell the user to run the `mien login <profile> --service ...` command **themselves** in their own terminal (the hidden `getpass` prompt keeps it out of argv/history), **or**
  - Use a credential reference, not the value: `mien login <profile> --service <svc> --secret-cmd 'op read op://Vault/item/field'` (also works with `gcloud secrets versions access`, `security find-generic-password`, etc.). The `op://…` reference is safe to appear in history; the secret never does.
  - For Google, a pre-existing refresh token can be piped: `… --refresh-token-stdin < tokenfile` with the client secret via `--secret-cmd`.
- **Don't switch the active profile in this shell** if the user is asking for a one-off in another identity — use `mien exec <other> -- <cmd>` so the parent shell stays clean.
- **Don't use the agent's native Google/Slack/Atlassian/Notion connectors** when `mien` is configured — they are single-account and bypass the user's vault.

## References

- `references/setup-flow.md` — conversational setup: walk a fresh user from zero to a working profile
- `references/schema.md` — config file format
- `references/bootstrap.md` — first-time setup per backend (manual, for users who'd rather type the commands themselves)
- `references/usage.md` — recipes for common tasks
- `references/concurrency.md` — what each variable/file isolates vs. shares, and directory-pinned identity rules
- `references/troubleshooting.md` — common errors
