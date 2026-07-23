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
moza-use personal            # the wrapper keys the ephemeral files to this shell ($$)
gh pr list
gcloud projects list
```

The exports live in *this* shell only. A second terminal is unaffected, and a new shell
starts with no profile.

## Pin an identity to a project

Give a profile the directories it owns, and work in those directories runs as that
identity without naming it:

```jsonc
"profiles": {
  "work":     { "default_for": ["*/Projects/acme*"] },
  "personal": { "default_for": ["*/Projects/moza"] }
}
```

```bash
moza which                     # → work
moza run -- gh pr list
```

Useful when several agent sessions run at once: each one is in its own project
directory, so each gets its own identity with no coordination between them.

## Activate (AI agent)

Agent harnesses run each command in a fresh shell, so an `eval` from an earlier tool call
has already been discarded — silently. Prefer a stateless form:

```bash
moza run -- gh pr list                 # if the directory pins an identity
moza exec personal -- gh pr list       # otherwise, name it

# capture the token; never let it reach stdout on its own
TOKEN=$(moza token google --profile personal) && curl -s -H "Authorization: Bearer $TOKEN" \
  'https://gmail.googleapis.com/gmail/v1/users/me/profile'
```

If a sequence genuinely needs one shell, keep the `eval` and the commands in a single
invocation. See the skill's *Activation pattern* section.

## Verify the live identity before something destructive

`moza whoami` prints what the config says a profile is — fast, offline, no network. `moza
whoami --live` goes further: it asks GitHub, AWS, and Google who the profile *actually*
authenticates as and compares that to the config.

```bash
moza whoami personal            # offline: what the profile claims to be
moza whoami --live personal     # verified: who the providers say you are
```

`--live` exits non-zero on a mismatch (wrong identity) or a dead credential (revoked or
expired token), and those are reported distinctly since they need different remedies. A
provider that could not be reached is shown but does not fail the check.

Two limits worth knowing before you rely on the exit code as a gate: **AWS is reported, not
verified** — a profile name is not an ARN, so there is no configured value to compare and a
wrong-but-valid AWS account will not trip the gate; and **slack/atlassian/notion/oci are not
probed yet**, so `--live` lists them as unchecked rather than pretending it verified them.
The gate is trustworthy for GitHub and Google. Chain it before anything you cannot take back:

```bash
moza whoami --live work && moza exec work -- gh pr merge 123
```

## Cross-identity one-off

```bash
moza exec work -- gh pr list
```

## Adding secrets without leaving a trace

Adding a credential mid-task — "the Slack key is in this file", "here's a fresh
PAT" — is routine. Every `moza login` secret is read without ever touching `argv`,
shell history, or `ps`: interactively through a hidden `getpass` prompt, or from
stdin / a helper command. Every backend then stores it without argv exposure too —
`macos_keychain` and `keyring` through in-process Keychain / Secret Service
bindings, `gcp_secret_manager` and `oci_vault` over their APIs. Pick the recipe
that matches where the secret already lives.

### From a file on disk

The secret is sitting in a file (a saved token, an exported key). Redirect the
file into `--token-stdin` — the path appears in history, the secret does not:

```bash
moza login work --service slack --workspace team-a --token-stdin < ./slack-key.txt
moza login work --service github --username u --token-stdin < ~/tokens/gh-work
```

Delete the file afterward if it was only a hand-off (`rm ./slack-key.txt`); the
secret now lives in the backend.

### From a credential manager (a reference, not the value)

The secret lives in 1Password, GCP Secret Manager, the macOS Keychain, etc. Pass
`--secret-cmd` a command that *fetches* it — only the reference reaches history,
never the secret. `moza` runs the command and reads its stdout:

```bash
moza login work --service github --username u \
  --secret-cmd 'op read op://Private/github-work/token'
moza login work --service aws --access-key-id AKIA... \
  --secret-cmd 'gcloud secrets versions access latest --secret=aws-work'
```

Equivalently, pipe the manager's output into `--token-stdin`
(`op read … | moza login … --token-stdin`) — same guarantee, the value never
becomes an argument.

### By hand, in your own terminal

No file, no manager — you have the secret and want to paste it. Run `moza login`
yourself (**not** through an AI agent's non-interactive shell) and answer the
hidden prompt:

```bash
moza login work --service github --username u
#   → "Paste a GitHub token:" (input hidden, nothing logged)
```

### Google (two secrets)

Google needs a client secret *and* a refresh token; combine any two mechanisms
above — here a manager reference for the client secret and a file for the token:

```bash
moza login work --service google --email me@x.com --client-id <id> \
  --secret-cmd 'op read op://Private/google-oauth/client_secret' \
  --refresh-token-stdin < ~/saved-refresh-token
```

Rule of thumb: never type or paste a secret as a CLI argument, and never ask an
AI agent to run `moza login` for you — its shell can't answer a hidden prompt, so
the secret would end up in the session transcript. Hand it a file (`--token-stdin
< path`) or a `--secret-cmd` reference instead.

## Reuse on a second machine

Secrets already live in the cloud backend; the config manifest carries the
profile map. On the new machine:

```bash
gcloud auth application-default login --account=<bootstrap-email>
gcloud auth application-default set-quota-project <sm-project>
moza init --backend gcp_secret_manager --project <sm-project> \
  --bootstrap-email <bootstrap-email>
#   → "Found an existing moza config (N profiles: ...). Import it? [Y/n]"
moza-use <profile>
```

The commands above are the **GCP Secret Manager** flow; an `oci_vault` backend
uses the same `moza init` import prompt but a different bootstrap (an OCI API key
in `~/.oci/config`, no ADC / quota-project step).

`moza init --no-import` skips the import prompt. `moza init --yes` auto-imports
without asking. A non-interactive run *without* `--yes` does **not** auto-import:
the confirmation prompt aborts, and because `init` has already written a fresh
empty config by that point, you are left with no profiles. Pass `--yes` or
`--no-import` explicitly when running `init` from a script or an agent — and note
that `--yes` means trusting whatever the backend manifest contains. Later, re-pull with `moza sync` (`--dry-run` to preview) or force-upload
local state with `moza push`. `moza sync` and `moza push` require a cloud backend
(`gcp_secret_manager` / `oci_vault`); they are a no-op or error on
`macos_keychain`.
