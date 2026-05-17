# Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `backend health check failed: PERMISSION_DENIED` (GCP) | Bootstrap account lacks `roles/secretmanager.viewer` | Grant the role on the secrets project |
| `OAuth completed but no refresh token` | Google did not return a refresh token (account already has consent) | Revoke at myaccount.google.com → re-run `hat login --service google` |
| `gcloud` still uses old account after `hat use` | Wrapper not sourced; you ran `hat use` instead of `hat-use` | `eval "$(hat use ...)"` or `source shell/hat.zsh` |
| `gh` ignores `GH_TOKEN` | `GITHUB_TOKEN` set in env (precedence) | `unset GITHUB_TOKEN` |
| `hat token google` fails with 401 | Refresh token revoked | `hat login personal --service google` again |
| `--secret-cmd failed (exit N)` | The helper command errored (wrong op:// ref, not signed in) | Run the command alone first; `op signin` / `gcloud auth login` as needed |
| `--secret-cmd produced empty output` | Command succeeded but printed nothing | Check the reference path; ensure the field exists |
| Secret leaked into shell history / agent transcript | Passed as a CLI arg, or an agent ran `hat login` | Rotate the secret; re-add via hidden prompt or `--secret-cmd` reference |
