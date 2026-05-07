# Conversational setup flow

Use this when the user has just installed `hat` and wants the agent to walk them through configuration. Drive the conversation — gather information one question at a time, run the non-interactive commands yourself, and hand off to the user only when a secret or browser flow is unavoidable.

## State detection (always run first)

```
hat doctor
```

- Exit 0 with profiles listed → already configured. Don't re-run setup; help with whatever the user actually asked for.
- Exit non-zero with `no config — run hat init first` → fresh install. Proceed with setup below.
- `hat: command not found` → CLI isn't installed. Tell the user to install it first (e.g. `uv tool install git+https://github.com/arinyaho/hat`) and stop.

## Step 1 — Pick a backend

Ask the user (one question, multiple choice):

> Where should `hat` keep your secrets?
> 1. **macOS Keychain** — zero setup, machine-local
> 2. **GCP Secret Manager** — encrypted at rest, syncs across machines, requires a GCP project you own
> 3. **OCI Vault** — same idea, on Oracle Cloud

Recommend (1) if the user has no preference and is on macOS. (2) is best for users who already use GCP and want cross-device sync.

## Step 2 — Backend prerequisites

### macOS Keychain
Nothing to do. Skip to Step 3.

### GCP Secret Manager

Run preflight first to surface the gaps:

```bash
hat preflight --backend gcp_secret_manager --project <project-id> --account <email> --json
```

Parse the JSON. For each `ok: false` finding, address its `fix` line:

| Failed check | Action |
|---|---|
| `gcloud installed` | Tell user to install Google Cloud SDK; stop. |
| `project '...' accessible` | Run `gcloud projects list --account=<email>` (you can run this) and ask the user which project ID to use. The display name is *not* the ID. |
| `Secret Manager API enabled` | You can run the fix yourself: `gcloud services enable secretmanager.googleapis.com --project=<id> --account=<email>`. Confirm with the user before doing it (it touches their cloud account). |
| `ADC present` | **Hand off to user.** This opens a browser. Tell them: "Run this in your terminal: `gcloud auth application-default login --account=<email>`. Let me know when done." |

After all checks pass, run:

```bash
hat init --backend gcp_secret_manager --project <id> --bootstrap-email <email>
```

Then verify:

```bash
hat doctor
```

If `ADC quota project` is missing, fix it: `gcloud auth application-default set-quota-project <id>`.

### OCI Vault

```bash
hat preflight --backend oci_vault --json
```

If `~/.oci/config` is missing, hand off — OCI setup involves API key generation in their console. Direct the user to run `oci setup config` or the bootstrap doc, then come back.

Once ready:

```bash
hat init --backend oci_vault --vault-ocid <ocid> --compartment-ocid <ocid> --region <region>
```

## Step 3 — Add a profile

Ask the user:
- What should the profile be called? (e.g. `personal`, `work`, `cryptolab`)
- Which services to wire up? (any combination of Google, GitHub, Slack)

### Google

```bash
hat login <profile> --service google --email <email> --client-id <oauth-client-id>
```

The `--client-id` requires an OAuth Desktop client. If the user doesn't have one, walk them through:
1. Open `https://console.cloud.google.com/apis/credentials?project=<bootstrap-project>`
2. Create Credentials → OAuth client ID → Application type: Desktop app
3. For a Workspace org project, set consent screen to **Internal** to avoid the 7-day testing-mode refresh-token expiry. For personal Gmail, External + add yourself as test user.
4. Copy client ID + secret.

After they have it, the `hat login` command will open a browser for the OAuth flow. **The client secret prompt requires user input** — hand off:

> Run this in your terminal: `hat login <profile> --service google --email <email> --client-id <id>`. It'll prompt for the client secret and open a browser.

### GitHub (PAT only)

If you have the PAT in some safe place the user already trusts (1Password CLI, env var, file), use stdin:

```bash
op read 'op://Personal/GitHub/PAT' | hat login <profile> --service github --username <user> --token-stdin
```

Or hand off entirely:

> Run: `hat login <profile> --service github --username <user>`. Paste your PAT when prompted.

### GitHub SSH (optional but recommended for cloning)

```bash
hat login <profile> --service github --ssh-key-path ~/.ssh/id_<profile>     # path only (per-device)
hat login <profile> --service github --ssh-key      ~/.ssh/id_<profile>     # store contents in backend (cross-device)
```

Per-device keys (path) are the security best practice; backend-stored keys are more convenient for users with multiple machines.

### Slack

```bash
hat login <profile> --service slack --workspace <label>
```

Hand off — paste the `xoxp-...` token at the prompt. Or pipe via `--token-stdin`.

## Step 4 — Verify

```bash
hat list
hat-use <profile>
hat status
```

`hat status` should show the profile is active with the expected env vars. Done.

## Rules for the agent

- **Never put a secret in a tool-call argument.** Use `--token-stdin` with a pipe from a trusted source, or hand off to the user's terminal.
- **Hand off browser flows.** OAuth, ADC login — these can't run under the Bash tool's stdin/stdout.
- **One question at a time.** Don't dump all backend choices + project + email in one message.
- **Show preflight failures verbatim.** The `fix` field already has actionable copy.
- **Don't run `gcloud auth login` or `gcloud config set` in Bash.** They mutate global state outside `hat`'s ephemeral model.
