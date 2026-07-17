---
name: moza
description: Use when the user wants to act as a specific identity/profile across Google (Gmail/Calendar/Drive/GCP), GitHub, Slack, Atlassian, Notion, AWS, or OCI — e.g., "as my work account", "switch to <name>", "post in <workspace>", "send mail from <email>". Activates per-shell credentials for `gh`, `gcloud`, `bq`, `aws`, `oci`, and `curl` calls without polluting other agent sessions.
version: 0.3.0
author: arinyaho
license: MIT
compatibility: works best with `moza` on PATH; falls back to source if available
metadata:
  hermes:
    tags: [identity, credentials, multi-account, gcp, github, slack, atlassian, notion, aws, oci]
    related_skills: []
---

# moza — Multi-identity credential router

The user maintains multiple identities, each bundling a Google account (Gmail/Calendar/Drive + GCP) and optionally a GitHub account, one or more Slack workspaces, an Atlassian account (Jira/Confluence), a Notion integration token, AWS credentials, and/or an OCI profile. Use `moza` to activate the right identity in this shell session.

## When to use

Trigger any time:
- The user names a profile (`personal`, `work-foo`, etc.) and asks for an action that needs auth.
- The user asks "as <email>" / "from <email>" / "with my <something> account".
- A multi-account task (one profile per agent session) — `moza` is what isolates them.
- The user wants to call Atlassian APIs (Jira, Confluence) under a specific identity.
- The user wants to call the Notion API under a specific identity.
- The user wants to run AWS CLI / SDK calls under a specific identity.
- The user wants to run OCI CLI calls under a specific identity.

If the user has not configured `moza`, **don't just punt** — drive the conversational setup flow described in `references/setup-flow.md`. Detect state with `moza doctor` (or `moza list` if doctor fails), then guide the user step by step.

## Invoking moza

Before running any `moza` command, resolve the binary:

```bash
# Prefer installed binary; fall back to source repo
if command -v moza &>/dev/null; then
  MOZA="moza"
elif [ -f "$HOME/Projects/moza/src/moza/__main__.py" ]; then
  MOZA="uv run --project $HOME/Projects/moza moza"
else
  echo "moza not found — clone https://github.com/arinyaho/moza and run: uv tool install ."
  exit 1
fi
```

Use `$MOZA` instead of `moza` in all subsequent commands.

## Core commands

```
$MOZA list                          # see profiles
$MOZA status                        # what is active in *this* shell
$MOZA use <profile>                 # prints `export ...`; eval to activate
$MOZA exec <profile> -- <cmd...>    # run cmd with the profile's env (no shell mutation)
$MOZA token google                  # mint a fresh google access token (for curl)
```

## Activation pattern

```bash
eval "$($MOZA use work-foo)"
gh pr list                        # uses GH_TOKEN
gcloud projects list              # uses CLOUDSDK_ACTIVE_CONFIG_NAME
bq ls -p                           # ditto
```

For Gmail/Calendar/Drive (no helper in v1 — use curl):

```bash
TOKEN=$(moza token google)
curl -s -H "Authorization: Bearer $TOKEN" \
  'https://gmail.googleapis.com/gmail/v1/users/me/messages?q=from:foo'
```

For Slack (multi-workspace per profile):

```bash
TOKEN=$(jq -r '."team-a"' "$MOZA_SLACK_TOKENS")
curl -s -H "Authorization: Bearer $TOKEN" \
  'https://slack.com/api/conversations.list'
```

If the profile has only one workspace, `$MOZA_SLACK_DEFAULT_TOKEN` is also exported.

For Atlassian (Jira/Confluence):

```bash
TOKEN=$(moza token atlassian)
EMAIL=$ATLASSIAN_EMAIL
curl -s -u "$EMAIL:$TOKEN" \
  "$ATLASSIAN_BASE_URL/rest/api/3/issue/PROJ-123"
```

`ATLASSIAN_EMAIL`, `ATLASSIAN_API_TOKEN`, and `ATLASSIAN_BASE_URL` are also exported directly by `moza use`.

For Notion:

```bash
TOKEN=$(moza token notion)
curl -s -H "Authorization: Bearer $TOKEN" -H "Notion-Version: 2022-06-28" \
  https://api.notion.com/v1/users/me
```

`NOTION_TOKEN` is also exported directly by `moza use`.

For AWS:

```bash
aws s3 ls                          # uses AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY or AWS_PROFILE
aws sts get-caller-identity        # verify active identity
```

`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_PROFILE`, and `AWS_DEFAULT_REGION` are exported by `moza use`.

For OCI:

```bash
oci iam user get --user-id <ocid>  # uses OCI_CLI_PROFILE / OCI_CLI_CONFIG_FILE
```

`OCI_CLI_PROFILE` and `OCI_CLI_CONFIG_FILE` are exported by `moza use`.

## Important rules

- **Never paste resolved tokens into the conversation.** Use shell expansion (`$GH_TOKEN`, `$(moza token google)`) so the token resolves at execution time and never appears in tool-call arguments.
- **Always activate a profile via `eval "$(moza use <profile>)"` or the `moza-use` wrapper — never run `moza use` bare.** As an extra safety net `moza use` writes exports to a 0600 ephemeral file and only prints a `source …; rm …` one-liner, so a missed `eval` no longer leaks tokens to stdout. On a real TTY `moza use` refuses outright (use `moza-use` or `eval`).
- **Never run `moza login` yourself to enter a secret.** The agent's shell is non-interactive, so you would have to put the secret in the command — which lands in the session transcript and shell history. Instead:
  - Tell the user to run the `moza login <profile> --service ...` command **themselves** in their own terminal (the hidden `getpass` prompt keeps it out of argv/history), **or**
  - Use a credential reference, not the value: `moza login <profile> --service <svc> --secret-cmd 'op read op://Vault/item/field'` (also works with `gcloud secrets versions access`, `security find-generic-password`, etc.). The `op://…` reference is safe to appear in history; the secret never does.
  - For Google, a pre-existing refresh token can be piped: `… --refresh-token-stdin < tokenfile` with the client secret via `--secret-cmd`.
- **Don't switch the active profile in this shell** if the user is asking for a one-off in another identity — use `moza exec <other> -- <cmd>` so the parent shell stays clean.
- **Don't use the agent's native Google/Slack/Atlassian/Notion connectors** when `moza` is configured — they are single-account and bypass the user's vault.

## References

- `references/setup-flow.md` — conversational setup: walk a fresh user from zero to a working profile
- `references/schema.md` — config file format
- `references/bootstrap.md` — first-time setup per backend (manual, for users who'd rather type the commands themselves)
- `references/usage.md` — recipes for common tasks
- `references/troubleshooting.md` — common errors
