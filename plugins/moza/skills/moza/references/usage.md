# Usage recipes

## Add a Google identity

You need an OAuth Desktop client in *some* GCP project (does not have to be the same as the secrets backend project). Get its client ID and client secret.

```bash
hat login personal --service google --email me@example.com --client-id <id>
# paste the client secret when prompted
# follow the browser flow that opens
```

## Add a GitHub identity (paste a PAT)

```bash
hat login personal --service github
# enter username, paste a fine-grained or classic PAT
```

## Add a Slack identity (one workspace at a time)

```bash
hat login personal --service slack --workspace team-a
# paste an xoxp- user token
```

## Activate

```bash
eval "$(hat use personal)"  # or: hat-use personal
gh pr list
gcloud projects list
```

## Cross-identity one-off

```bash
hat exec work -- gh pr list
```

## Adding secrets without leaving a trace

Every `hat login` secret is read via a hidden `getpass` prompt — the value never
reaches `argv`, shell history, or `ps`. Three ways to supply it:

```bash
# 1. Interactive (run it yourself, NOT via an agent's non-interactive shell)
hat login work --service github --username u
#   → "Paste a GitHub token:" (input hidden, nothing logged)

# 2. From a credential manager — only the *reference* hits history, never the secret
hat login work --service github --username u \
  --secret-cmd 'op read op://Private/github-work/token'
hat login work --service aws --access-key-id AKIA... \
  --secret-cmd 'gcloud secrets versions access latest --secret=aws-work'

# 3. From a pipe (reference/path in history, not the secret)
op read op://Private/slack-team-a/token | \
  hat login work --service slack --workspace team-a --token-stdin
```

Google needs two secrets (client secret + refresh token):

```bash
hat login work --service google --email me@x.com --client-id <id> \
  --secret-cmd 'op read op://Private/google-oauth/client_secret' \
  --refresh-token-stdin < ~/saved-refresh-token
```

Rule of thumb: never type or paste a secret as a CLI argument, and never ask an
AI agent to run `hat login` for you — its shell can't answer a hidden prompt, so
the secret would end up in the session transcript. Hand it a `--secret-cmd`
reference instead.

## Reuse on a second machine

Secrets already live in the cloud backend; the config manifest carries the
profile map. On the new machine:

```bash
gcloud auth application-default login --account=<bootstrap-email>
gcloud auth application-default set-quota-project <sm-project>
hat init --backend gcp_secret_manager --project <sm-project> \
  --bootstrap-email <bootstrap-email>
#   → "Found an existing hat config (N profiles: ...). Import it? [Y/n]"
eval "$(hat use <profile>)"
```

`hat init --no-import` skips the prompt. Later, re-pull with `hat sync`
(`--dry-run` to preview) or force-upload local state with `hat push`.
