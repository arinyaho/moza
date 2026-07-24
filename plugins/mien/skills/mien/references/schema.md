# Config schema (`~/.config/mien/config.json`)

Default location: `~/.config/mien/config.json`. Override with `MIEN_CONFIG=/some/path`.

Top level:

```jsonc
{
  "$schema_version": 1,
  "secrets_backend": { "type": "...", /* options */ },
  "bootstrap": { /* optional, backend-specific */ },
  "secret_naming": { "default": "...", "slack_token": "..." },
  "profiles": { "<name>": { "google": {...}|null, "github": {...}|null, "slack": [...] } }
}
```

## Backends

- `gcp_secret_manager`: `{"type": "gcp_secret_manager", "project": "<gcp-project>"}`
- `oci_vault`: `{"type": "oci_vault", "vault_ocid": "...", "compartment_ocid": "...", "region": "..."}`
- `macos_keychain`: `{"type": "macos_keychain", "service_prefix": "mien-"}`
- `keyring`: `{"type": "keyring", "service_prefix": "mien-"}` — Linux Secret Service / Windows Credential Locker; free, no cloud; requires a desktop session (does NOT work headless)

## Profile blocks

All three are optional per profile.

### `google`
```jsonc
{
  "email": "...",
  "oauth_client_id": "...",
  "oauth_client_secret_ref": "<backend-ref>",
  "refresh_token_ref":       "<backend-ref>",
  "adc_ref":                 "<backend-ref>|null",
  "gcloud_config_name":      "<typically equals profile name>",
  "default_project":         "..."|null,
  "gcloud_login_required":   false
}
```

### `github`
```jsonc
{ "username": "...", "host": "github.com", "token_ref": "<backend-ref>" }
```

### `slack` (array)
```jsonc
[{ "workspace": "team-a", "team_id": null, "user_token_ref": "<backend-ref>" }]
```

### `notion`
```jsonc
{ "api_token_ref": "<backend-ref>" }
```

### `default_for` (array)

Directory globs this profile claims as its default identity. Resolved by `mien
which` and `mien run`.

```jsonc
["*/Projects/acme*", "*/work/*"]
```

A scope covers the directory itself and everything under it; a sibling sharing a
prefix is not covered (`*/Projects/acme` does not capture `acme-fork`). The
longest matching scope wins, and equally specific scopes on different profiles
are an error rather than a coin flip. An active `MIEN_PROFILE` overrides the
directory, with a warning on stderr when the two disagree; if it names a profile
the config does not have, the command fails instead of resolving to nothing.

`~` and `$VAR` are expanded before matching, so `~/Projects/acme` and
`$HOME/Projects/acme` are equivalent to the literal path. A variable that is
**unset or set to the empty string** is left literal and therefore matches
nothing, as is `~` when `HOME` is empty. This differs deliberately from the
`project_env` shell, where zsh expands both to the empty string — there
`$UNSET/Projects/acme` becomes `/Projects/acme`, which is *disjoint* from the
intended tree (it silently covers an unrelated path and stops covering the one
you meant), and a scope that is nothing but a reference — `$UNSET`, or
`$UNSET/*`, which normalizes to the same base — collapses to the pattern `/*`
and covers every absolute path. For identity, failing closed beats either
outcome.

Must be a list of strings. A bare string is rejected rather than coerced: JSON
has no way to tell a one-element list from a scalar, and silently accepting
`"default_for": "*/Projects/acme"` would iterate it character by character, one
of which is `*`.

Distinct from `project_env`, which maps directories to environment *values*;
`default_for` maps directories to *which identity you are*.

### `owns_remotes` (array)

Git-remote globs this profile owns. Where `default_for` claims identity by
directory, `owns_remotes` claims it by the repository's `origin` remote — by
*what the repo is* rather than where it sits — so it fits repositories kept side
by side with no per-employer directory convention.

```jsonc
["github.com/acme-*/*", "github.com/me/*"]
```

The remote is normalized before matching: the scheme, any `user@`, and a trailing
`.git` are stripped and an ssh `:` becomes `/`, so every form of the same URL
(`https://…`, `git@github.com:…`, `ssh://…`) reduces to one canonical
`host/path`, lower-cased. A pattern matches that form and everything under it, so
a bare owner (`github.com/acme`) claims the owner and its repositories. The
longest match wins; an exact tie is an error, as with `default_for`. A profile may
list several — a personal account and the organizations it also manages. Same
list-of-strings rule: a bare string is rejected, not coerced.

**Advisory only.** `owns_remotes` drives the status line (`mien statusline`) — it
displays whose repository this is and warns when the active `MIEN_PROFILE`
disagrees. It is deliberately *not* consulted by `mien which` / `run` / `exec`,
which choose an identity that *acts*: a checked-out repository controls its own
`origin`, and letting a repository select an acting identity would violate the
rule that a clone cannot influence which identity acts. A directory scope is part
of your own config and may select an acting identity; a repository's self-declared
remote may not.

### `project_env` (array)

Non-secret environment values applied ambiently by directory. `mien env sync`
renders every profile's scopes into `~/.config/mien/ambient.zsh` as
`case "$PWD/" in <base>/*)` blocks and wires `~/.zshenv` to source it.

```jsonc
[{ "match": "*/work/acme", "env": { "AWS_PROFILE": "work" } }]
```

`match` follows the same directory-glob rules as `default_for` (the directory
itself and everything under it; a trailing `/*` or `/` is normalized away).
Values are non-secret only — no secrets-backend refs.

**Variable references in `match` are evaluated in `~/.zshenv`, which zsh reads
before `~/.zshrc` and `~/.zprofile`.** Anything the user exports from their own
dotfiles is therefore unset at match time and expands to nothing, with the
consequences described under `default_for` above: `$WORK_ROOT/*` becomes `/*`
and applies that scope's env — `AWS_PROFILE` included — in every directory. Only
parameters that already exist that early (`$HOME`, `$USER` and the like, set by
zsh itself or inherited from the login process) are safe; `~` is safe too, since
tilde expansion consults the password database. `$TMPDIR` is deliberately *not*
treated as safe — macOS launchd sets it, but stock sshd and a default Linux PAM
do not, and mien pins no platform. `mien env sync` prints a warning naming the
profile and scope for any other reference, and still writes the file — an
existing working config is not broken by the check.

## Reserved backend secret name

`mien-config-manifest` is reserved: `mien` stores a non-secret snapshot of
`config.json` (refs and identifiers only — no secret values) under this name in
cloud backends (`gcp_secret_manager`, `oci_vault`). It is pushed automatically
after every `mien login` / `mien logout`. Do not create a profile whose rendered
secret name collides with it.
