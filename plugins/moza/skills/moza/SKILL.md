---
name: hat
description: Use when the user wants to act as a specific identity/profile across Google (Gmail/Calendar/Drive/GCP), GitHub, Slack, Atlassian, AWS, or OCI — e.g., "as my work account", "switch to <name>", "post in <workspace>", "send mail from <email>". Activates per-shell credentials for `gh`, `gcloud`, `bq`, `aws`, `oci`, and `curl` calls without polluting other agent sessions.
version: 0.2.0
author: arinyaho
license: MIT
compatibility: works best with `hat` on PATH; falls back to source if available
metadata:
  hermes:
    tags: [identity, credentials, multi-account, gcp, github, slack, atlassian, aws, oci]
    related_skills: []
---

# hat — Multi-identity credential router

The user maintains multiple identities, each bundling a Google account (Gmail/Calendar/Drive + GCP) and optionally a GitHub account, one or more Slack workspaces, an Atlassian account (Jira/Confluence), AWS credentials, and/or an OCI profile. Use `hat` to activate the right identity in this shell session.

## When to use

Trigger any time:
- The user names a profile (`personal`, `work-foo`, etc.) and asks for an action that needs auth.
- The user asks "as <email>" / "from <email>" / "with my <something> account".
- A multi-account task (one profile per agent session) — `hat` is what isolates them.
- The user wants to call Atlassian APIs (Jira, Confluence) under a specific identity.
- The user wants to run AWS CLI / SDK calls under a specific identity.
- The user wants to run OCI CLI calls under a specific identity.

If the user has not configured `hat`, **don't just punt** — drive the conversational setup flow described in `references/setup-flow.md`. Detect state with `hat doctor` (or `hat list` if doctor fails), then guide the user step by step.

## Invoking hat

Before running any `hat` command, resolve the binary:

```bash
# Prefer installed binary; fall back to source repo
if command -v hat &>/dev/null; then
  HAT="hat"
elif [ -f "$HOME/Projects/hat/src/hat/__main__.py" ]; then
  HAT="uv run --project $HOME/Projects/hat hat"
else
  echo "hat not found — clone https://github.com/arinyaho/moza and run: uv tool install ."
  exit 1
fi
```

Use `$HAT` instead of `hat` in all subsequent commands.

## Core commands

```
$HAT list                          # see profiles
$HAT status                        # what is active in *this* shell
$HAT use <profile>                 # prints `export ...`; eval to activate
$HAT exec <profile> -- <cmd...>    # run cmd with the profile's env (no shell mutation)
$HAT token google                  # mint a fresh google access token (for curl)
```

## Activation pattern

```bash
eval "$($HAT use work-foo)"
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

For Atlassian (Jira/Confluence):

```bash
TOKEN=$(hat token atlassian)
EMAIL=$ATLASSIAN_EMAIL
curl -s -u "$EMAIL:$TOKEN" \
  "$ATLASSIAN_BASE_URL/rest/api/3/issue/PROJ-123"
```

`ATLASSIAN_EMAIL`, `ATLASSIAN_API_TOKEN`, and `ATLASSIAN_BASE_URL` are also exported directly by `hat use`.

For AWS:

```bash
aws s3 ls                          # uses AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY or AWS_PROFILE
aws sts get-caller-identity        # verify active identity
```

`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_PROFILE`, and `AWS_DEFAULT_REGION` are exported by `hat use`.

For OCI:

```bash
oci iam user get --user-id <ocid>  # uses OCI_CLI_PROFILE / OCI_CLI_CONFIG_FILE
```

`OCI_CLI_PROFILE` and `OCI_CLI_CONFIG_FILE` are exported by `hat use`.

## Important rules

- **Never paste resolved tokens into the conversation.** Use shell expansion (`$GH_TOKEN`, `$(hat token google)`) so the token resolves at execution time and never appears in tool-call arguments.
- **Always activate a profile via `eval "$(hat use <profile>)"` or the `hat-use` wrapper — never run `hat use` bare.** As an extra safety net `hat use` writes exports to a 0600 ephemeral file and only prints a `source …; rm …` one-liner, so a missed `eval` no longer leaks tokens to stdout. On a real TTY `hat use` refuses outright (use `hat-use` or `eval`).
- **Never run `hat login` yourself to enter a secret.** The agent's shell is non-interactive, so you would have to put the secret in the command — which lands in the session transcript and shell history. Instead:
  - Tell the user to run the `hat login <profile> --service ...` command **themselves** in their own terminal (the hidden `getpass` prompt keeps it out of argv/history), **or**
  - Use a credential reference, not the value: `hat login <profile> --service <svc> --secret-cmd 'op read op://Vault/item/field'` (also works with `gcloud secrets versions access`, `security find-generic-password`, etc.). The `op://…` reference is safe to appear in history; the secret never does.
  - For Google, a pre-existing refresh token can be piped: `… --refresh-token-stdin < tokenfile` with the client secret via `--secret-cmd`.
- **Don't switch the active profile in this shell** if the user is asking for a one-off in another identity — use `hat exec <other> -- <cmd>` so the parent shell stays clean.
- **Don't use the agent's native Google/Slack/Atlassian connectors** when `hat` is configured — they are single-account and bypass the user's vault.

## References

- `references/setup-flow.md` — conversational setup: walk a fresh user from zero to a working profile
- `references/schema.md` — config file format
- `references/bootstrap.md` — first-time setup per backend (manual, for users who'd rather type the commands themselves)
- `references/usage.md` — recipes for common tasks
- `references/troubleshooting.md` — common errors
