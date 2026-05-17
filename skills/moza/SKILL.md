---
name: hat
description: Use when the user wants to act as a specific identity/profile across Google (Gmail/Calendar/Drive/GCP), GitHub, or Slack — e.g., "as my work account", "switch to <name>", "post in <workspace>", "send mail from <email>". Activates per-shell credentials for `gh`, `gcloud`, `bq`, and `curl` calls without polluting other Claude sessions.
version: 0.1.0
author: arinyaho
license: MIT
compatibility: requires the `hat` CLI on PATH — install from https://github.com/arinyaho/hat
metadata:
  hermes:
    tags: [identity, credentials, multi-account, gcp, github, slack]
    related_skills: []
---

# hat — Multi-identity credential router

The user maintains multiple identities, each bundling a Google account (Gmail/Calendar/Drive + GCP) and optionally a GitHub account and one or more Slack workspaces. Use `hat` to activate the right identity in this shell session.

## When to use

Trigger any time:
- The user names a profile (`personal`, `work-foo`, etc.) and asks for an action that needs auth.
- The user asks "as <email>" / "from <email>" / "with my <something> account".
- A multi-account task (one profile per Claude session) — `hat` is what isolates them.

If the user has not configured `hat`, **don't just punt** — drive the conversational setup flow described in `references/setup-flow.md`. Detect state with `hat doctor` (or `hat list` if doctor fails), then guide the user step by step.

## Core commands

```
hat list                          # see profiles
hat status                        # what is active in *this* shell
hat use <profile>                 # prints `export ...`; eval to activate
hat-use <profile>                 # zsh/bash wrapper that does the eval
hat exec <profile> -- <cmd...>    # run cmd with the profile's env (no shell mutation)
hat token google                  # mint a fresh google access token (for curl)
```

## Activation pattern

```bash
eval "$(hat use work-foo)"
gh pr list                        # uses GH_TOKEN
gcloud projects list              # uses CLOUDSDK_ACTIVE_CONFIG_NAME
bq ls -p                           # ditto
```

For Gmail/Calendar/Drive (no helper in v1 — use curl):

```bash
TOKEN=$(hat token google)
curl -s -H "Authorization: Bearer $TOKEN" \
  'https://gmail.googleapis.com/gmail/v1/users/me/messages?q=from:foo'
```

For Slack (multi-workspace per profile):

```bash
TOKEN=$(jq -r '."team-a"' "$HAT_SLACK_TOKENS")
curl -s -H "Authorization: Bearer $TOKEN" \
  'https://slack.com/api/conversations.list'
```

If the profile has only one workspace, `$HAT_SLACK_DEFAULT_TOKEN` is also exported.

## Important rules

- **Never paste resolved tokens into the conversation.** Use shell expansion (`$GH_TOKEN`, `$(hat token google)`) so the token resolves at execution time and never appears in tool-call arguments.
- **Don't switch the active profile in this shell** if the user is asking for a one-off in another identity — use `hat exec <other> -- <cmd>` so the parent shell stays clean.
- **Don't call the claude.ai-hosted Gmail/Calendar/Drive/Slack MCP servers** when `hat` is configured — they are single-account and bypass the user's vault.

## References

- `references/setup-flow.md` — conversational setup: walk a fresh user from zero to a working profile
- `references/schema.md` — config file format
- `references/bootstrap.md` — first-time setup per backend (manual, for users who'd rather type the commands themselves)
- `references/usage.md` — recipes for common tasks
- `references/troubleshooting.md` — common errors
