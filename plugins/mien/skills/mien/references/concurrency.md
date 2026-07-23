# Concurrency semantics: what is isolated, what is shared

Running several sessions at once — one per identity, one per agent — is mien's core use case, so the isolation boundary is a specification, not a claim. This page states exactly what each mien-set variable and file isolates, and where the isolation stops because mien is selecting into a store the underlying provider shares.

The short version: **every variable mien sets lives only in the shell that activated it**, and the ephemeral credential files it writes are keyed to that shell's pid. What mien does *not* isolate is the on-disk provider stores those variables point into (`~/.config/gcloud`, `~/.aws`, `~/.oci/config`), the secrets backend, and the config manifest — those are shared by design, and concurrent *writes* to them race.

## Environment variables

Each variable is exported only into the shell that ran `mien use` / `mien exec` / `mien run`; a second shell that did not is unaffected. The isolation question that remains is whether the *store the variable selects into* is per-shell or shared.

| Variable | Selects / points into | Isolated across shells? |
|---|---|---|
| `MIEN_PROFILE` | — (marker: which profile is active) | per-shell |
| `MIEN_EPHEMERAL_DIR` | `$TMPDIR/mien` | value per-shell; the directory itself is shared |
| `CLOUDSDK_ACTIVE_CONFIG_NAME` | `~/.config/gcloud/configurations/` | **shared store** — see warnings |
| `CLOUDSDK_CORE_PROJECT` | — (value) | per-shell |
| `GOOGLE_APPLICATION_CREDENTIALS` | `$TMPDIR/mien/<pid>-<profile>-adc.json` | per-shell (pid-keyed file) |
| `GH_TOKEN` | — (token value in env) | per-shell |
| `GIT_SSH_COMMAND` | pid-keyed ephemeral key, or a static `ssh_key_path` | per-shell if ephemeral; the static key file is shared |
| `MIEN_SLACK_TOKENS` | `$TMPDIR/mien/<pid>-<profile>-slack.json` | per-shell (pid-keyed file) |
| `MIEN_SLACK_DEFAULT_TOKEN` | — (token value in env) | per-shell |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | — (values) | per-shell |
| `AWS_PROFILE` | `~/.aws/credentials`, `~/.aws/config` | **shared store** — see warnings |
| `AWS_DEFAULT_REGION` | — (value) | per-shell |
| `OCI_CLI_PROFILE` | `~/.oci/config` (or the file `OCI_CLI_CONFIG_FILE` names) | **shared store** — see warnings |
| `OCI_CLI_CONFIG_FILE` | the config file it names | **shared store** |
| `ATLASSIAN_EMAIL` / `ATLASSIAN_API_TOKEN` / `ATLASSIAN_BASE_URL` | — (values) | per-shell |
| `NOTION_TOKEN` | — (token value in env) | per-shell |

`mien unset` / `mien-unset` clears exactly these variables from the current shell.

## Files

| File | Isolation |
|---|---|
| `$TMPDIR/mien/<pid>-<profile>-{adc,ssh_key,slack}.json` | **per-shell** — keyed to the owner pid (`mien-use` passes `$$`), 0600 |
| `$TMPDIR/mien/env-<hex>.sh` | **per-invocation** — the loader `mien use` writes; sourced, then removed by the same one-liner |
| `$TMPDIR/mien/` (the directory) | **shared** — every shell's ephemeral files land here; `mien doctor --gc` sweeps files whose owning pid is dead, across all shells |
| `$MIEN_CONFIG` (default `~/.config/mien/config.json`) | **shared** — the profile map every shell reads |
| secrets backend (macOS Keychain / GCP Secret Manager / OCI Vault / keyring) | **shared** — where the tokens actually live |
| `~/.config/gcloud/`, `~/.aws/`, `~/.oci/config` | **shared** — the provider stores mien selects into but never isolates |
| `~/.zshenv` | **shared, persistent** — only touched if you run `mien env sync` |

## Where isolation stops: shared-store races

A per-shell *variable* pointing into a *shared* store means reads are safe to run in parallel, but two sessions writing that store concurrently can corrupt or clobber each other. mien selects the identity; it does not serialize the provider's own writes.

- **gcloud.** `CLOUDSDK_ACTIVE_CONFIG_NAME` is per-shell, but the configuration store under `~/.config/gcloud` is shared. Two sessions running an interactive `gcloud auth login`, `gcloud config set`, or an ADC login *at the same time* race on that store — one can overwrite the other's freshly written credentials. Read-only `gcloud` calls under distinct configs are fine; serialize the logins.
- **AWS.** `AWS_PROFILE` is per-shell; `~/.aws/credentials` and `~/.aws/config` are shared. Concurrent `aws configure` or `aws sso login` writes to the same file race the same way. mien-supplied `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` sidestep the file entirely and are fully per-shell.
- **OCI.** `OCI_CLI_PROFILE` is per-shell; `~/.oci/config` is shared. Concurrent edits to that file race.
- **The mien manifest and backend.** `$MIEN_CONFIG` and the secrets backend are shared. `mien login`, `mien push`, and `mien sync` mutate them; running two of those against the same manifest at once is a write race. Activating profiles (`mien use` / `exec` / `run`) only *reads* the manifest, so any number of those run safely in parallel.
- **The ephemeral directory.** `$TMPDIR/mien` is shared and `mien doctor --gc` sweeps it globally, but it deletes only files whose owning pid is dead — so a live session's pid-keyed files are never reclaimed out from under it. (This is why the files are keyed to the calling shell rather than to mien's own short-lived process.)

## Directory-pinned identity

A profile can claim directories with `default_for` globs, so work in those directories resolves to that identity without naming it (`mien which`, `mien run`). The resolution rules:

- **What a scope covers.** A scope covers the directory it names *and* everything beneath it. `~` and `$VAR` are expanded the way the shell would expand them; a `*` spans `/`. A variable that is unset or set-but-empty is left literal on purpose (so it matches nothing) rather than widening the scope — silently widening a scope is how credentials get misrouted.
- **When scopes overlap, the most specific wins.** Specificity is the length of the (expanded, normalized) glob: a scope nested inside another is longer, so it wins. This is a lexical rule — it cannot tell that `*/Projects/acme` is *semantically* narrower than a longer but broader literal path.
- **A tie is refused, not guessed.** If two profiles claim a directory with equal specificity, resolution raises rather than picking one — guessing would misroute credentials silently. Narrow one profile's `default_for`, or name the profile explicitly.
- **An activated profile overrides the directory.** If `MIEN_PROFILE` is set in the shell (e.g. a terminal where someone ran `mien-use work`, inherited into every agent command it launches), `mien run` uses it over whatever the directory would resolve to. `mien which` reports the conflict — but only as a warning on stderr, and it still exits 0. So when the identity matters, read what `which` printed, or name the profile with `mien exec` and leave nothing to inherit.

Because each concurrent session is typically in its own project directory, directory-pinned identity is what lets many sessions run at once with no coordination between them — provided no ambient `MIEN_PROFILE` is overriding the directory in one of them.
