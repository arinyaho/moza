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

## Reserved backend secret name

`moza-config-manifest` is reserved: `moza` stores a non-secret snapshot of
`config.json` (refs and identifiers only — no secret values) under this name in
cloud backends (`gcp_secret_manager`, `oci_vault`). It is pushed automatically
after every `moza login` / `moza logout`. Do not create a profile whose rendered
secret name collides with it.
