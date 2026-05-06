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
