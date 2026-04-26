# Bootstrap

Run `hat init` and answer prompts. Per-backend setup:

## GCP Secret Manager

Requires `gcloud` and a project with Secret Manager API enabled.

```bash
gcloud services enable secretmanager.googleapis.com --project=<project>
gcloud auth application-default login --account=<bootstrap-email>
hat init
# pick (1) gcp_secret_manager, supply project + bootstrap email
hat doctor
```

The bootstrap account's ADC at `~/.config/gcloud/application_default_credentials.json` is the seed used to read every other identity's material out of Secret Manager. Per-profile ADCs (the GCP credentials that other identities use) are *backed up* into Secret Manager by `hat login --service google`, and *restored* into ephemeral files by `hat use`.

## OCI Vault

Requires `~/.oci/config` with API key PEM, and a Vault + Compartment created in the OCI console.

```bash
hat init  # pick (2), supply vault OCID, compartment OCID, region
hat doctor
```

## macOS Keychain

Zero setup beyond a logged-in user.

```bash
hat init  # pick (3), service prefix defaults to "hat-"
hat doctor
```
