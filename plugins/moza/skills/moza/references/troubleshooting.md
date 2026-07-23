# Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `backend health check failed: PERMISSION_DENIED` (GCP) | Bootstrap account lacks `roles/secretmanager.viewer` | Grant the role on the secrets project |
| `OAuth completed but no refresh token` | Google did not return a refresh token (account already has consent) | Revoke at myaccount.google.com → re-run `moza login --service google` |
| `gcloud` still uses old account after `moza use` | Wrapper not sourced; you ran `moza use` instead of `moza-use` | Install the wrappers with `eval "$(moza shell-init)"` and use `moza-use`, or `eval "$(moza use --owner-pid $$ ...)"` |
| `gh` acts as the wrong account under `moza exec` | Profile has no GitHub token, so `moza` sets no `GH_TOKEN` and the ambient `GH_TOKEN`/`GITHUB_TOKEN` survives (`exec` overlays, it does not scrub) | `moza login <profile> --service github`, or unset both in the calling shell |
| `moza run` used the wrong identity, and exited 0 | `MOZA_PROFILE` was inherited from the launching terminal and beats the directory. Common for an agent session started where someone had run `moza-use <profile>`. `moza which` reports it, but only on stderr, and still exits 0 | `moza-unset` in that shell (bare `moza unset` only prints the commands), or name the profile: `moza exec <profile> -- ...` |
| `moza which` exits 1 with `no profile claims <dir>` | No `default_for` scope covers this directory — or the scope names a variable that is unset or empty, which is left literal on purpose so it matches nothing | Add or widen a `default_for` scope; use a literal path or `~` instead of a variable |
| `moza env sync` warns that a scope variable is unexpandable | `~/.zshenv` is read before `~/.zshrc`/`~/.zprofile`, so a variable you define there is unset when the scope is evaluated — `$VAR/*` collapses to `/*` and matches everything | Write a literal path or `~` in `project_env.match` |
| `moza token google` fails with 401 | Refresh token revoked | `moza login personal --service google` again |
| `--secret-cmd failed (exit N)` | The helper command errored (wrong op:// ref, not signed in) | Run the command alone first; `op signin` / `gcloud auth login` as needed |
| `--secret-cmd produced empty output` | Command succeeded but printed nothing | Check the reference path; ensure the field exists |
| Secret leaked into shell history / agent transcript | Passed as a CLI arg, or an agent ran `moza login` | Rotate the secret; re-add via hidden prompt or `--secret-cmd` reference |
