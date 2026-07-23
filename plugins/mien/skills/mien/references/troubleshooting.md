# Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `backend health check failed: PERMISSION_DENIED` (GCP) | Bootstrap account lacks `roles/secretmanager.viewer` | Grant the role on the secrets project |
| `OAuth completed but no refresh token` | Google did not return a refresh token (account already has consent) | Revoke at myaccount.google.com → re-run `mien login --service google` |
| `gcloud` still uses old account after `mien use` | Wrapper not sourced; you ran `mien use` instead of `mien-use` | Install the wrappers with `eval "$(mien shell-init)"` and use `mien-use`, or `eval "$(mien use --owner-pid $$ ...)"` |
| `gh` acts as the wrong account under `mien exec` | Profile has no GitHub token, so `mien` sets no `GH_TOKEN` and the ambient `GH_TOKEN`/`GITHUB_TOKEN` survives (`exec` overlays, it does not scrub) | `mien login <profile> --service github`, or unset both in the calling shell |
| `mien run` used the wrong identity, and exited 0 | `MIEN_PROFILE` was inherited from the launching terminal and beats the directory. Common for an agent session started where someone had run `mien-use <profile>`. `mien which` reports it, but only on stderr, and still exits 0 | `mien-unset` in that shell (bare `mien unset` only prints the commands), or name the profile: `mien exec <profile> -- ...` |
| `mien which` exits 1 with `no profile claims <dir>` | No `default_for` scope covers this directory — or the scope names a variable that is unset or empty, which is left literal on purpose so it matches nothing | Add or widen a `default_for` scope; use a literal path or `~` instead of a variable |
| `mien env sync` warns that a scope variable is unexpandable | `~/.zshenv` is read before `~/.zshrc`/`~/.zprofile`, so a variable you define there is unset when the scope is evaluated — `$VAR/*` collapses to `/*` and matches everything | Write a literal path or `~` in `project_env.match` |
| `mien token google` fails with 401 | Refresh token revoked | `mien login personal --service google` again |
| `--secret-cmd failed (exit N)` | The helper command errored (wrong op:// ref, not signed in) | Run the command alone first; `op signin` / `gcloud auth login` as needed |
| `--secret-cmd produced empty output` | Command succeeded but printed nothing | Check the reference path; ensure the field exists |
| Secret leaked into shell history / agent transcript | Passed as a CLI arg, or an agent ran `mien login` | Rotate the secret; re-add via hidden prompt or `--secret-cmd` reference |
