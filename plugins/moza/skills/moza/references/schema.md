# Config schema (`~/.config/moza/config.json`)

Default location: `~/.config/moza/config.json`. Override with `MOZA_CONFIG=/some/path`.

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
- `macos_keychain`: `{"type": "macos_keychain", "service_prefix": "moza-"}`
- `keyring`: `{"type": "keyring", "service_prefix": "moza-"}` — Linux Secret Service / Windows Credential Locker; free, no cloud; requires a desktop session (does NOT work headless)

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

Directory globs this profile claims as its default identity. Resolved by `moza
which` and `moza run`.

```jsonc
["*/Projects/acme*", "*/work/*"]
```

A scope covers the directory itself and everything under it; a sibling sharing a
prefix is not covered (`*/Projects/acme` does not capture `acme-fork`). The
longest matching scope wins, and equally specific scopes on different profiles
are an error rather than a coin flip. An active `MOZA_PROFILE` overrides the
directory, with a warning on stderr when the two disagree; if it names a profile
the config does not have, the command fails instead of resolving to nothing.

`~` and `$VAR` are expanded before matching, so `~/Projects/acme` and
`$HOME/Projects/acme` are equivalent to the literal path. A variable that is
**unset or set to the empty string** is left literal and therefore matches
nothing, as is `~` when `HOME` is empty. This differs deliberately from the
`project_env` shell, where zsh expands both to the empty string — there
`$UNSET/Projects/acme` becomes `/Projects/acme`, a broader scope, and a scope of
just `$UNSET` covers everything. For identity, failing closed beats silently
claiming more directories.

Must be a list of strings. A bare string is rejected rather than coerced: JSON
has no way to tell a one-element list from a scalar, and silently accepting
`"default_for": "*/Projects/acme"` would iterate it character by character, one
of which is `*`.

Distinct from `project_env`, which maps directories to environment *values*;
`default_for` maps directories to *which identity you are*.

## Reserved backend secret name

`moza-config-manifest` is reserved: `moza` stores a non-secret snapshot of
`config.json` (refs and identifiers only — no secret values) under this name in
cloud backends (`gcp_secret_manager`, `oci_vault`). It is pushed automatically
after every `moza login` / `moza logout`. Do not create a profile whose rendered
secret name collides with it.
