# Conversational setup flow

Use this when the user has just installed `mien` and wants the agent to walk them through configuration. Drive the conversation — gather information one question at a time, run the non-interactive commands yourself, and hand off to the user only when a secret or browser flow is unavoidable.

## State detection (always run first)

```
mien doctor
```

- Exit 0 with profiles listed → already configured. Don't re-run setup; help with whatever the user actually asked for.
- Exit non-zero with `no config — run mien init first` → fresh install. Proceed with setup below.
- `mien: command not found` → CLI isn't installed. Tell the user to install it first (e.g. `uv tool install git+https://github.com/arinyaho/mien`) and stop.

## Step 1 — Pick a backend

Ask the user (one question, multiple choice):

> Where should `mien` keep your secrets?
> 1. **macOS Keychain** — zero setup, machine-local
> 2. **GCP Secret Manager** — encrypted at rest, syncs across machines, requires a GCP project you own
> 3. **OCI Vault** — same idea, on Oracle Cloud
> 4. **keyring** — Linux Secret Service (GNOME Keyring / KWallet) or Windows Credential Locker; free, no cloud, no macOS, requires a desktop session (does NOT work headless)

Recommend (1) if the user has no preference and is on macOS. Recommend (4) for Linux or Windows users who want local storage with no cloud dependency. (2) is best for users who already use GCP and want cross-device sync.

## Step 2 — Backend prerequisites

### macOS Keychain
Nothing to do. Skip to Step 3.

### GCP Secret Manager

Run preflight first to surface the gaps:

```bash
mien preflight --backend gcp_secret_manager --project <project-id> --account <email> --json
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
mien init --backend gcp_secret_manager --project <id> --bootstrap-email <email>
```

Then verify:

```bash
mien doctor
```

If `ADC quota project` is missing, fix it: `gcloud auth application-default set-quota-project <id>`.

### OCI Vault

```bash
mien preflight --backend oci_vault --json
```

If `~/.oci/config` is missing, hand off — OCI setup involves API key generation in their console. Direct the user to run `oci setup config` or the bootstrap doc, then come back.

Once ready:

```bash
mien init --backend oci_vault --vault-ocid <ocid> --compartment-ocid <ocid> --region <region>
```

## Step 3 — Add a profile

Ask the user:
- What should the profile be called? (e.g. `personal`, `work`, `work-b`)
- Which services to wire up? (any combination of Google, GitHub, Slack)

### Google

```bash
mien login <profile> --service google --email <email> --client-id <oauth-client-id>
```

The `--client-id` requires an OAuth Desktop client. If the user doesn't have one, walk them through:
1. Open `https://console.cloud.google.com/apis/credentials?project=<bootstrap-project>`
2. Create Credentials → OAuth client ID → Application type: Desktop app
3. For a Workspace org project, set consent screen to **Internal** to avoid the 7-day testing-mode refresh-token expiry. For personal Gmail, External + add yourself as test user.
4. Copy client ID + secret.

After they have it, the `mien login` command will open a browser for the OAuth flow. **The client secret prompt requires user input** — hand off:

> Run this in your terminal: `mien login <profile> --service google --email <email> --client-id <id>`. It'll prompt for the client secret and open a browser.

### GitHub (PAT only)

If you have the PAT in some safe place the user already trusts (1Password CLI, env var, file), use stdin:

```bash
op read 'op://Personal/GitHub/PAT' | mien login <profile> --service github --username <user> --token-stdin
```

Or hand off entirely:

> Run: `mien login <profile> --service github --username <user>`. Paste your PAT when prompted.

### GitHub SSH (optional but recommended for cloning)

```bash
mien login <profile> --service github --ssh-key-path ~/.ssh/id_<profile>     # path only (per-device)
mien login <profile> --service github --ssh-key      ~/.ssh/id_<profile>     # store contents in backend (cross-device)
```

Per-device keys (path) are the security best practice; backend-stored keys are more convenient for users with multiple machines.

### Slack

```bash
mien login <profile> --service slack --workspace <label>
```

Hand off — paste the `xoxp-...` token at the prompt. Or pipe via `--token-stdin`.

## Step 4 — Verify

```bash
mien list
mien-use <profile>
mien status
```

`mien status` should show the profile is active with the expected env vars. Done.

## Rules for the agent

- **Never put a secret in a tool-call argument.** Use `--token-stdin` with a pipe from a trusted source, or hand off to the user's terminal.
- **Hand off browser flows.** OAuth, ADC login — these can't run under the Bash tool's stdin/stdout.
- **One question at a time.** Don't dump all backend choices + project + email in one message.
- **Show preflight failures verbatim.** The `fix` field already has actionable copy.
- **Don't run `gcloud auth login` or `gcloud config set` in Bash.** They mutate global state outside `mien`'s ephemeral model.
