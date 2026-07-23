# Bootstrap

Run `mien init` and answer prompts. Per-backend setup:

## GCP Secret Manager

Requires `gcloud` and a project with Secret Manager API enabled.

```bash
# Pick the BOOTSTRAP_EMAIL whose Secret Manager you'll seed `mien` from.
# Pick the SECRETS_PROJECT (a project owned by that account) where secrets will live.

# 1) Enable Secret Manager on that project, AS that account
gcloud services enable secretmanager.googleapis.com \
  --project="$SECRETS_PROJECT" \
  --account="$BOOTSTRAP_EMAIL"

# 2) Set ADC for that account (this is the only ADC `mien` will read globally)
gcloud auth application-default login --account="$BOOTSTRAP_EMAIL"

# 3) Run init — supplies project ID + bootstrap email; verifies connectivity
mien init

# 4) Re-verify any time
mien doctor
```

### Two gcloud "accounts" — don't confuse them

`gcloud` has two independent account layers, and they do NOT share state:

| Layer | Set with | Used by |
|---|---|---|
| **CLI account** | `gcloud auth login <EMAIL>` | `gcloud projects list`, `gcloud services enable`, `bq`, `gsutil` |
| **ADC** | `gcloud auth application-default login --account=<EMAIL>` | Python `google-cloud-*` libraries, `mien`'s Secret Manager access |

So:

- Always pass `--account=<BOOTSTRAP_EMAIL>` to one-off `gcloud` commands operating on a project owned by that account, OR set it active first with `gcloud config set account <BOOTSTRAP_EMAIL>`. Otherwise you'll get `PERMISSION_DENIED` from a different active CLI account.
- `gcloud projects list` shows projects accessible to the **CLI account**, not ADC. To enumerate as the bootstrap account, use `gcloud projects list --account="$BOOTSTRAP_EMAIL"`. Or query via API directly with the ADC token to be sure:
  ```bash
  curl -s -H "Authorization: Bearer $(gcloud auth application-default print-access-token)" \
    https://cloudresourcemanager.googleapis.com/v1/projects | jq '.projects[].projectId'
  ```
- The bootstrap ADC at `~/.config/gcloud/application_default_credentials.json` is the *only* ADC `mien` ever reads from disk. Per-profile ADCs are synthesized on the fly from refresh tokens at `mien use` time and written to ephemeral files pointed to by `GOOGLE_APPLICATION_CREDENTIALS`. The global ADC location is never overwritten by `mien`.

### Project ID, not project name

`mien init` rejects values containing spaces or uppercase letters because GCP project IDs are lowercase, hyphenated, often with a numeric suffix (e.g., `my-first-project-12345`). The display name (e.g., "My First Project") is different. Find the ID with:

```bash
gcloud projects list --account="$BOOTSTRAP_EMAIL"
```

The `PROJECT_ID` column is what you want.

## OCI Vault

Requires `~/.oci/config` with API key PEM, and a Vault + Compartment created in the OCI console.

```bash
mien init  # pick (2), supply vault OCID, compartment OCID, region
mien doctor
```

## macOS Keychain

Zero setup beyond a logged-in user.

```bash
mien init  # pick (3), service prefix defaults to "mien-"
mien doctor
```

## keyring (Linux Secret Service / Windows Credential Locker)

Free, no cloud, no macOS. Requires a running desktop Secret Service (GNOME Keyring, KWallet, or Windows Credential Locker). Does NOT work on headless servers.

```bash
mien init  # pick (4), service prefix defaults to "mien-"
mien doctor
```
