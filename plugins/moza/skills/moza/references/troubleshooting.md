# Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `backend health check failed: PERMISSION_DENIED` (GCP) | Bootstrap account lacks `roles/secretmanager.viewer` | Grant the role on the secrets project |
| `OAuth completed but no refresh token` | Google did not return a refresh token (account already has consent) | Revoke at myaccount.google.com → re-run `moza login --service google` |
| `gcloud` still uses old account after `moza use` | Wrapper not sourced; you ran `moza use` instead of `moza-use` | `eval "$(moza use ...)"` or `source shell/moza.zsh` |
| `gh` acts as the wrong account under `moza exec` | Profile has no GitHub token, so `moza` sets no `GH_TOKEN` and the ambient `GH_TOKEN`/`GITHUB_TOKEN` survives (`exec` overlays, it does not scrub) | `moza login <profile> --service github`, or unset both in the calling shell |
| `moza token google` fails with 401 | Refresh token revoked | `moza login personal --service google` again |
| `--secret-cmd failed (exit N)` | The helper command errored (wrong op:// ref, not signed in) | Run the command alone first; `op signin` / `gcloud auth login` as needed |
| `--secret-cmd produced empty output` | Command succeeded but printed nothing | Check the reference path; ensure the field exists |
| Secret leaked into shell history / agent transcript | Passed as a CLI arg, or an agent ran `moza login` | Rotate the secret; re-add via hidden prompt or `--secret-cmd` reference |
