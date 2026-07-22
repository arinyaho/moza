# Usage recipes

## Add a Google identity

You need an OAuth Desktop client in *some* GCP project (does not have to be the same as the secrets backend project). Get its client ID and client secret.

```bash
moza login personal --service google --email me@example.com --client-id <id>
# paste the client secret when prompted
# follow the browser flow that opens
```

## Add a GitHub identity (paste a PAT)

```bash
moza login personal --service github
# enter username, paste a fine-grained or classic PAT
```

## Add a Slack identity (one workspace at a time)

```bash
moza login personal --service slack --workspace team-a
# paste an xoxp- user token
```

## Add a Notion identity

```bash
moza login personal --service notion
# paste a Notion integration token
```

## Activate (interactive shell)

```bash
eval "$(moza use personal)"  # or: moza-use personal
gh pr list
gcloud projects list
```

The exports live in *this* shell only. A second terminal is unaffected, and a new shell
starts with no profile.

## Activate (AI agent)

Agent harnesses run each command in a fresh shell, so an `eval` from an earlier tool call
has already been discarded — silently. Prefer the stateless form:

```bash
moza exec personal -- gh pr list
TOKEN=$(moza token google --profile personal) && curl -s -H "Authorization: Bearer $TOKEN" \
  'https://gmail.googleapis.com/gmail/v1/users/me/profile'
```

If a sequence genuinely needs one shell, keep the `eval` and the commands in a single
invocation. See the skill's *Activation pattern* section.

## Cross-identity one-off

```bash
moza exec work -- gh pr list
```

## Adding secrets without leaving a trace

Every `moza login` secret is read via a hidden `getpass` prompt — the value never
reaches `argv`, shell history, or `ps`. Three ways to supply it:

```bash
# 1. Interactive (run it yourself, NOT via an agent's non-interactive shell)
moza login work --service github --username u
#   → "Paste a GitHub token:" (input hidden, nothing logged)

# 2. From a credential manager — only the *reference* hits history, never the secret
moza login work --service github --username u \
  --secret-cmd 'op read op://Private/github-work/token'
moza login work --service aws --access-key-id AKIA... \
  --secret-cmd 'gcloud secrets versions access latest --secret=aws-work'

# 3. From a pipe (reference/path in history, not the secret)
op read op://Private/slack-team-a/token | \
  moza login work --service slack --workspace team-a --token-stdin
```

Google needs two secrets (client secret + refresh token):

```bash
moza login work --service google --email me@x.com --client-id <id> \
  --secret-cmd 'op read op://Private/google-oauth/client_secret' \
  --refresh-token-stdin < ~/saved-refresh-token
```

Rule of thumb: never type or paste a secret as a CLI argument, and never ask an
AI agent to run `moza login` for you — its shell can't answer a hidden prompt, so
the secret would end up in the session transcript. Hand it a `--secret-cmd`
reference instead.

## Reuse on a second machine

Secrets already live in the cloud backend; the config manifest carries the
profile map. On the new machine:

```bash
gcloud auth application-default login --account=<bootstrap-email>
gcloud auth application-default set-quota-project <sm-project>
moza init --backend gcp_secret_manager --project <sm-project> \
  --bootstrap-email <bootstrap-email>
#   → "Found an existing moza config (N profiles: ...). Import it? [Y/n]"
eval "$(moza use <profile>)"
```

The commands above are the **GCP Secret Manager** flow; an `oci_vault` backend
uses the same `moza init` import prompt but a different bootstrap (an OCI API key
in `~/.oci/config`, no ADC / quota-project step).

`moza init --no-import` skips the import prompt; `moza init --yes` (or any
non-interactive run) auto-imports without asking — useful for agent-driven
setup. Later, re-pull with `moza sync` (`--dry-run` to preview) or force-upload
local state with `moza push`. `moza sync` and `moza push` require a cloud backend
(`gcp_secret_manager` / `oci_vault`); they are a no-op or error on
`macos_keychain`.
