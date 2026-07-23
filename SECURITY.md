# Security

`moza` holds credentials. This document says what it protects, what it does not, and where every secret it touches actually lives — including the parts that are uncomfortable. A tool in this category earns trust by being specific about its limits, so the sections below name them rather than implying they do not exist.

Everything here is stated against the code. If you find a claim the code does not support, that is a bug in this file and worth reporting.

## Protection goals, and what is not protected

**Isolating identities between concurrent shells.** Activation only ever writes to the current process environment and to files keyed by that process. Two terminals, or two AI agent sessions, can hold different identities at once without coordinating.

*Not protected:* the credential stores those identities point at are shared. `AWS_PROFILE` selects among credentials in `~/.aws`; `CLOUDSDK_ACTIVE_CONFIG_NAME` selects a gcloud configuration whose credential store is global. Two sessions that run an interactive `gcloud auth login` at the same time will race.

**Keeping secret values out of your home directory.** GitHub tokens, Slack tokens, Atlassian and Notion tokens, Google refresh tokens, and AWS keys live in a secrets backend, not in a dotfile. What lands on disk locally is references and identifiers.

*Not protected:* several services are *selected*, not replaced — see [What stays in your home directory](#what-stays-in-your-home-directory). And "not in your home directory" is not "not on disk": activation writes short-lived credential files under `$TMPDIR`, described below.

**Keeping secrets out of transcripts, shell history, and `ps`.** `moza use` never prints a secret; it writes the exports to a mode-0600 file and prints a one-liner that sources and deletes it. On a real terminal it refuses to run at all unless you pass `--print`. `moza login` reads secrets through a hidden prompt, a `--secret-cmd` reference, or stdin.

*Not protected:* `moza token <service>` prints a token to stdout by design — that is its purpose — and for Atlassian and Notion that token is long-lived, not a short-lived access token. Whatever captures that stdout holds the secret. The `macos_keychain` backend also passes secrets through `security(1)`'s argv on write; see [Known weaknesses](#known-weaknesses).

**Hiding secrets from an AI agent: NOT a goal.** This is the most important line in this document. `moza` puts credentials into the environment so that ordinary tools pick them up. An agent that can run commands in that environment can read them, and so can every process it starts. If your threat model is a prompt-injected agent exfiltrating a token, `moza` is the wrong layer — you want a credential proxy that never lets the value reach the agent at all. `moza` trades that isolation for working with every CLI and SDK unmodified, and for letting a person choose which identity to act as.

**Integrity of the configuration: NOT protected, and the consequence is worse than misrouting.** The config file is plain JSON with no signature or checksum. Anything that can write it — or set `$MOZA_CONFIG` — decides which backend `moza` talks to and which directories map to which identity.

It also reaches further than that. A `project_env` value is emitted into `ambient.zsh` inside a double-quoted `export`, with only `\` and `"` escaped — `$` and backticks are left intact deliberately, because that is how a value like `$HOME/bin` is meant to work. `moza env sync` validates the result with `zsh -n`, which *parses* without executing, so a command substitution passes the gate. `~/.zshenv` then sources that file in **every** zsh you start, including non-interactive ones. So a `project_env` value is executable code, and anyone who can write your config — or your backend manifest, which `moza init --yes` imports without prompting — can run commands as you.

Treat the config file and the backend manifest as trusted input. Do not import a manifest you did not create.

**Non-repudiation: no protections attempted.** `moza` keeps no audit log. Nothing records which identity was activated when, or which command ran under it.

## What is stored where

| Location | Mode | Contents | Removed by |
|---|---|---|---|
| `~/.config/moza/config.json` (override with `$MOZA_CONFIG`) | 0600 | Backend type and options, bootstrap account, secret-name templates, per-profile identifiers and **references**. No secret value, with one exception: `project_env` values are stored verbatim, so a secret typed there lands here | nothing |
| `~/.config/moza/ambient.zsh` | 0600 | Generated `case` blocks exporting each profile's `project_env` values | rewritten by `moza env sync` |
| `~/.zshenv` (a marked region) | 0600 | One line sourcing `ambient.zsh` | nothing |
| `$TMPDIR/moza/<pid>-<profile>-adc.json` | 0600 | **Secret.** Google OAuth client secret + refresh token | see [Lifetime](#lifetime-and-cleanup) |
| `$TMPDIR/moza/<pid>-<profile>-ssh_key.json` | 0600 | **Secret.** A GitHub SSH private key | see [Lifetime](#lifetime-and-cleanup) |
| `$TMPDIR/moza/<pid>-<profile>-slack.json` | 0600 | **Secret.** Every Slack token on the profile, by workspace | see [Lifetime](#lifetime-and-cleanup) |
| `$TMPDIR/moza/env-<random>.sh` | 0600 | **Secret. The highest-value file here** — every exported variable, including every token, in one place | the `. '<path>' && rm -f '<path>'` one-liner `moza use` prints |
| Secrets backend | backend's own | Every secret value | `moza logout` |

`$TMPDIR/moza/` itself is created with your umask, so typically 0755. The files inside are 0600, but their **names encode the profile and PID**. Where `TMPDIR` is a shared `/tmp`, other local users can list which identities exist and when they are active. On macOS the default `TMPDIR` is a per-user 0700 directory, so that exposure does not apply there.

`moza` writes nowhere else. It never writes to `~/.ssh`, `~/.aws`, `~/.oci`, `~/.config/gh`, or gcloud's credential store. The one exception is `moza init` with the GCP backend, which runs `gcloud auth application-default set-quota-project` and so causes gcloud to update its own ADC file.

## The environment-variable surface

This is where a secret is most exposed, and it is worth being exact about who can see it.

Variables that carry a **secret value directly**: `GH_TOKEN`, `MOZA_SLACK_DEFAULT_TOKEN`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `ATLASSIAN_API_TOKEN`, `NOTION_TOKEN`.

Variables that carry a **path to a secret**: `GOOGLE_APPLICATION_CREDENTIALS`, `MOZA_SLACK_TOKENS`, and the key path inside `GIT_SSH_COMMAND`.

Variables that carry **only a selector**: `MOZA_PROFILE`, `MOZA_EPHEMERAL_DIR`, `CLOUDSDK_ACTIVE_CONFIG_NAME`, `CLOUDSDK_CORE_PROJECT`, `AWS_PROFILE`, `AWS_DEFAULT_REGION`, `OCI_CLI_PROFILE`, `OCI_CLI_CONFIG_FILE`, `ATLASSIAN_EMAIL`, `ATLASSIAN_BASE_URL`.

Once `moza use` has run in a shell, the first group is readable by that shell and **every process it starts afterwards** — an editor, a language server, a build script, an AI agent — whether or not that process has anything to do with the profile. On Linux, anything able to read `/proc/<pid>/environ` for your UID sees them; on macOS, `ps -E` does. There is no expiry and no scoping: the exposure is bounded by the shell's lifetime, and `moza-unset` is the only thing that ends it early. (Bare `moza unset` only prints the commands — like `moza use`, it cannot change the calling shell.)

`moza exec` and `moza run` narrow this considerably — the variables exist only for the duration of one child process — which is why they are the recommended form, especially for agents.

Neither form **scrubs**. The profile's variables are layered over the environment you already had. A profile with no AWS identity leaves an ambient `AWS_ACCESS_KEY_ID` untouched, so the child uses it. If you need certainty about a service the profile does not define, clear it yourself or check with that service's own identity command.

## What stays in your home directory

`moza` replaces a home-directory credential for: GitHub tokens, Slack, Atlassian, Notion, per-profile Google ADC, AWS in access-key mode, and GitHub SSH when the key was stored in the backend.

It only *selects among* credentials that remain on disk for:

| Service | What remains |
|---|---|
| AWS, profile mode | `~/.aws/credentials` or `~/.aws/config` — `moza` stores no credential and sets `AWS_PROFILE`, plus `AWS_DEFAULT_REGION` when the profile carries a region |
| OCI, always | `~/.oci/config` and the API-key PEM it names. `moza` stores no OCI secret at all |
| gcloud CLI identity | The gcloud configuration and its credential store. `CLOUDSDK_ACTIVE_CONFIG_NAME` names a configuration; it does not supply one |
| GitHub SSH, path mode | Your private key stays in `~/.ssh` |
| `moza`'s own backend access | The bootstrap Google ADC, for the GCP backend, or `~/.oci/config` for the OCI backend |
| `macos_keychain` backend | Your login keychain, `~/Library/Keychains/` — encrypted at rest, but the secrets are in `$HOME` |
| `keyring` backend | The OS credential store, typically `~/.local/share/keyrings` — same caveat |

So `moza` writing no token files into your home directory is true of the files it writes itself. It is not a claim that no credential of yours remains in `$HOME` — the table above is the list that does remain.

## Backends

| Backend | Where values live | Authenticated by | A compromise of that yields | Network |
|---|---|---|---|---|
| `gcp_secret_manager` | Google Secret Manager | Application Default Credentials | read, write and delete of every `moza` secret the principal's IAM allows, plus the config manifest | yes |
| `oci_vault` | OCI Vault | `~/.oci/config` and the API key it names | the same, scoped by OCI IAM | yes |
| `macos_keychain` | macOS login keychain | your logged-in session | every `moza-*` item | no |
| `keyring` | OS credential store | an unlocked desktop session | every stored item | no |

Compromise of the bootstrap credential is equivalent to compromise of every identity the cloud backends hold. It is the single most valuable thing on the machine and deserves the strongest protection you can give it.

**The manifest.** With a cloud backend, `moza` stores a copy of the configuration as a secret named `moza-config-manifest`, and pushes it after `moza login` and `moza logout`, on a best-effort basis — a failed push is a warning, not an error. `moza init` writes the local config without pushing, and `moza push` is the explicit manual path. It contains references and identifiers only — no secret value — with one exception: values you place in `project_env` are copied verbatim, so a secret typed there is uploaded. Do not put secrets in `project_env`.

Both cloud backends update the manifest in place on each push — a new version of one fixed secret — so the copy a second machine pulls tracks your latest config. (Nothing deletes the manifest; it is only ever rewritten.)

Two commands adopt that manifest. `moza init --yes` imports it without prompting, and `moza sync` pulls it and replaces the local config — also without prompting under `--yes`. Its interactive confirmation lists only profile *names*, so a changed `project_env` value shows up as `~ change: work` and nothing more. A backend an attacker controls can therefore redefine every profile — including which directories claim which identity, and including the `project_env` values that become executable code — through either path.

## Lifetime and cleanup

`moza exec` and `moza run` delete the credential files they created when the child exits — on normal exit, a non-zero exit, a signal, or Ctrl-C.

`moza use` deliberately leaves its files behind, because your shell needs them after the process ends. Cleaning them up is best-effort:

- The shell integration runs `moza doctor --gc` from an `EXIT` trap, but only when a profile is active in that shell.
- That command performs a backend health check first, so **offline, or with an expired bootstrap credential, nothing is swept.**
- A shell that never exits — a long-lived terminal, a multiplexer pane, an agent session — never fires the trap.

The practical consequence: sweeping is intent, not a guarantee. Assume a 0600 file may persist under `$TMPDIR` until something sweeps it, and treat `$TMPDIR` as sensitive.

The `env-<random>.sh` file deserves its own note, since it holds every exported secret in one place. `moza use` writes it and prints a one-liner that sources and then deletes it — so it is removed as soon as you `eval` the output. If you never do (you captured stdout instead, used `--print`, or the `source` failed so the `&& rm -f` never ran), it stays. The sweep only reclaims it after five minutes, and only when a `moza doctor --gc` actually runs, which the previous paragraph's conditions govern. Capturing `moza use` output without evaluating it therefore leaves a complete set of your credentials on disk.

`moza-unset` clears the variables. It does not delete anything on disk. Bare `moza unset` only prints the `unset` lines for you to eval, and unlike `moza use` it has no terminal guard, so it looks like it worked.

`moza logout` removes a secret from the backend — but not always immediately. On OCI it *schedules* deletion, which is cancellable for up to 30 days, so the value stays retrievable until that elapses. On GCP the secret and all its versions are destroyed at once; note though that re-running `moza login` for a service adds a new version without disabling the old ones, so rotating this way leaves the previous value readable until you delete the secret. Logout also does not reach into shells that already hold the value, or the files they point at — those keep working until the shell exits or a sweep runs.

## Known weaknesses

These are real and currently unfixed. They are tracked, and listed here rather than omitted.

- **The `macos_keychain` backend passes secrets through `security(1)`'s command line on write.** For the duration of that subprocess the plaintext is visible to anything that can list your processes. This contradicts the guarantee the rest of the credential-input path upholds. The `keyring` backend and both cloud backends do not have this problem.
- **`moza use`'s credential files are attributed to a process that has already exited**, so a garbage collection triggered by an unrelated shell can delete files a live session is still pointing at. The effect is breakage, not disclosure.
- **`moza env sync` rewrites `~/.zshenv` atomically**, which replaces the file and normalizes its mode to 0600. Content outside `moza`'s marked region is preserved, but hard links, ACLs and extended attributes on that file are not.
- **`$MOZA_CONFIG` is honoured without validation**, so anything able to set that variable redirects the whole configuration.
- **`--secret-cmd` runs its argument through a shell.** It is yours to supply, so it crosses no privilege boundary, but it is an execution path in a credential tool.
- **Storing a GitHub SSH private key in a cloud backend is offered without comment**, and nothing checks whether the key has a passphrase.

## Verifying a release

Releases are not currently signed, and installation is from source. Until that changes, verify by reading: the code is MIT-licensed and the storage surface is small enough to audit in an afternoon — the four functions that write to disk are in `config.py`, `ambient.py`, `ephemeral.py`, and `shell.py`.

## Reporting a vulnerability

Open a GitHub issue for anything already public, such as a wrong claim in this file. For something exploitable that is not yet public, use GitHub's private vulnerability reporting on this repository rather than an issue.

There is no bug bounty and no guaranteed response time — this is a single-maintainer project, and pretending otherwise would be its own kind of security theatre.
