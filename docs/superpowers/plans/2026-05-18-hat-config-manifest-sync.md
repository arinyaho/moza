# Config Manifest Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A second machine recovers all `hat` profiles automatically by reading a non-secret config manifest stored in the cloud secrets backend.

**Architecture:** Serialize the existing `config.json` (refs/identifiers only, no secret values) into a reserved backend secret `hat-config-manifest`. Push it automatically after every config-mutating command; offer to import it during `hat init`; expose `hat sync` / `hat push` for explicit control. A new `hat/manifest.py` keeps `config.py` free of backend dependencies.

**Tech Stack:** Python 3.10, Click, dataclasses, pytest + pytest-mock. Backend protocol: `SecretsBackend.{get,put,list}`.

---

## Notes for the implementer

- **Run tests with the project venv**, not bare pytest: `uv run python -m pytest ...`. Plain `uv run pytest` picks up a Homebrew interpreter lacking `google_auth_oauthlib` and fails collection on `test_cli.py` — that is a pre-existing environment quirk, not your bug.
- `backend.list(prefix=...)` returns canonical refs (e.g. `projects/P/secrets/NAME/versions/latest`); `backend.get(ref)` returns `bytes`; `backend.put(name, bytes)` returns a ref. Confirmed in `src/hat/backends/gcp.py`.
- `_config_to_dict` / `_config_from_dict` already exist in `config.py`. The schema-version check currently lives inline in `load_config`. Task 1 factors it out so the manifest path reuses it (DRY).

## File Structure

- **Create** `src/hat/manifest.py` — manifest constants + push/pull + `is_cloud_backend`.
- **Create** `tests/test_config.py` — round-trip tests for the new serialize/deserialize helpers (imports `hat.config` only; runs locally).
- **Create** `tests/test_manifest.py` — manifest unit tests with a fake backend (imports `hat.manifest`/`hat.config` only; runs locally).
- **Modify** `src/hat/config.py` — add `serialize_config` / `deserialize_config`; refactor `load_config` / `save_config` to use them.
- **Modify** `src/hat/cli.py` — `_save_and_sync` helper, reserved-name guard, wire push into `login`/`logout`, `init` import path + `--no-import`, new `sync` and `push` commands.
- **Modify** `tests/test_cli.py` — CLI behavior tests (run in CI / via `uv run python -m pytest`).
- **Modify** `plugins/moza/skills/moza/references/schema.md` and `usage.md` — document the reserved name and the cross-machine recipe.

---

### Task 1: Factor config (de)serialization helpers

**Files:**
- Modify: `src/hat/config.py`
- Test: `tests/test_config.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
import json

import pytest

from hat.config import (
    BackendConfig,
    Config,
    GitHubService,
    Profile,
    SecretNaming,
    deserialize_config,
    serialize_config,
)


def _cfg() -> Config:
    return Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="gcp_secret_manager", options={"project": "p1"}),
        bootstrap={"gcp_account": "me@x.com"},
        secret_naming=SecretNaming(
            default="hat-{profile}-{service}-{kind}",
            slack_token="hat-{profile}-slack-{workspace}-token",
        ),
        profiles={
            "work": Profile(
                name="work",
                github=GitHubService(username="u", host="github.com", token_ref="ref://gh"),
            )
        },
    )


def test_serialize_then_deserialize_roundtrips():
    cfg = _cfg()
    restored = deserialize_config(serialize_config(cfg))
    assert restored.profiles["work"].github.username == "u"
    assert restored.profiles["work"].github.token_ref == "ref://gh"
    assert restored.secrets_backend.type == "gcp_secret_manager"
    assert restored.secrets_backend.options["project"] == "p1"
    assert restored.bootstrap == {"gcp_account": "me@x.com"}


def test_deserialize_accepts_dict_and_str():
    cfg = _cfg()
    as_str = serialize_config(cfg)
    from_str = deserialize_config(as_str)
    from_dict = deserialize_config(json.loads(as_str))
    assert from_str.profiles.keys() == from_dict.profiles.keys()


def test_deserialize_rejects_bad_schema_version():
    bad = json.dumps({"$schema_version": 99, "secrets_backend": {"type": "macos_keychain"},
                       "bootstrap": {}, "secret_naming": {}, "profiles": {}})
    with pytest.raises(ValueError, match="Unsupported schema_version"):
        deserialize_config(bad)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'serialize_config'`.

- [ ] **Step 3: Add the helpers and refactor load/save**

In `src/hat/config.py`, add these two functions immediately after `def config_path()` (before `def load_config`):

```python
def serialize_config(cfg: Config) -> str:
    return json.dumps(_config_to_dict(cfg), indent=2, sort_keys=False)


def deserialize_config(raw: str | dict) -> Config:
    data = json.loads(raw) if isinstance(raw, str) else raw
    version = data.get("$schema_version", data.get("schema_version"))
    if version != SCHEMA_VERSION:
        raise ValueError(f"Unsupported schema_version {version!r}; expected {SCHEMA_VERSION}")
    return _config_from_dict(data)
```

Replace the body of `load_config` with:

```python
def load_config() -> Config | None:
    path = config_path()
    if not path.exists():
        return None
    return deserialize_config(path.read_text())
```

Replace the body of `save_config` with:

```python
def save_config(cfg: Config) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_config(cfg))
    path.chmod(0o600)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_config.py tests/test_env.py -v`
Expected: PASS (new config tests + the 9 existing env tests still green).

- [ ] **Step 5: Commit**

```bash
git add src/hat/config.py tests/test_config.py
git commit -m "refactor: factor serialize_config/deserialize_config helpers

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 2: Create the manifest module

**Files:**
- Create: `src/hat/manifest.py`
- Test: `tests/test_manifest.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_manifest.py`:

```python
import pytest

from hat.config import BackendConfig, Config, GitHubService, Profile, SecretNaming
from hat.manifest import (
    MANIFEST_SECRET_NAME,
    is_cloud_backend,
    pull_manifest,
    push_manifest,
)


class FakeBackend:
    def __init__(self):
        self.store: dict[str, bytes] = {}

    def put(self, name: str, value: bytes) -> str:
        self.store[name] = value
        return f"ref://{name}/versions/latest"

    def get(self, ref: str) -> bytes:
        name = ref.removeprefix("ref://").rsplit("/versions/", 1)[0]
        return self.store[name]

    def list(self, prefix: str | None = None) -> list[str]:
        return [
            f"ref://{n}/versions/latest"
            for n in self.store
            if prefix is None or n.startswith(prefix)
        ]


def _cfg(type_="gcp_secret_manager") -> Config:
    return Config(
        schema_version=1,
        secrets_backend=BackendConfig(type=type_, options={"project": "p1"}),
        bootstrap={"gcp_account": "me@x.com"},
        secret_naming=SecretNaming(
            default="hat-{profile}-{service}-{kind}",
            slack_token="hat-{profile}-slack-{workspace}-token",
        ),
        profiles={"work": Profile(name="work",
                                  github=GitHubService(username="u", host="github.com",
                                                       token_ref="ref://gh"))},
    )


def test_is_cloud_backend():
    assert is_cloud_backend(BackendConfig(type="gcp_secret_manager", options={}))
    assert is_cloud_backend(BackendConfig(type="oci_vault", options={}))
    assert not is_cloud_backend(BackendConfig(type="macos_keychain", options={}))


def test_push_then_pull_roundtrips():
    b = FakeBackend()
    push_manifest(_cfg(), b)
    assert MANIFEST_SECRET_NAME in b.store
    restored = pull_manifest(b)
    assert restored is not None
    assert restored.profiles["work"].github.token_ref == "ref://gh"


def test_pull_returns_none_when_absent():
    assert pull_manifest(FakeBackend()) is None


def test_pull_raises_on_bad_schema_version():
    b = FakeBackend()
    b.store[MANIFEST_SECRET_NAME] = b'{"$schema_version": 99, "secrets_backend": {"type": "macos_keychain"}, "bootstrap": {}, "secret_naming": {}, "profiles": {}}'
    with pytest.raises(ValueError, match="Unsupported schema_version"):
        pull_manifest(b)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_manifest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hat.manifest'`.

- [ ] **Step 3: Create `src/hat/manifest.py`**

```python
from __future__ import annotations

from hat.backends.base import SecretsBackend
from hat.config import BackendConfig, Config, deserialize_config, serialize_config

MANIFEST_SECRET_NAME = "hat-config-manifest"
_CLOUD_BACKENDS = {"gcp_secret_manager", "oci_vault"}


def is_cloud_backend(backend_cfg: BackendConfig) -> bool:
    return backend_cfg.type in _CLOUD_BACKENDS


def push_manifest(cfg: Config, backend: SecretsBackend) -> None:
    backend.put(MANIFEST_SECRET_NAME, serialize_config(cfg).encode("utf-8"))


def pull_manifest(backend: SecretsBackend) -> Config | None:
    refs = backend.list(prefix=MANIFEST_SECRET_NAME)
    if not refs:
        return None
    data = backend.get(refs[0])
    return deserialize_config(data.decode("utf-8"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_manifest.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/hat/manifest.py tests/test_manifest.py
git commit -m "feat: hat.manifest — push/pull config manifest to cloud backend

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Auto-push manifest after login/logout + reserved-name guard

**Files:**
- Modify: `src/hat/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_login_github_pushes_manifest(runner, hat_cfg, mocker):
    backend = mocker.patch("hat.cli.load_backend").return_value
    backend.put.return_value = "ref://gh-token"
    mocker.patch("hat.cli.pull_manifest", return_value=None)
    push = mocker.patch("hat.cli.push_manifest")
    runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "github"],
        input="y\nmyuser\nghp_token123\nn\n",
    )
    assert result.exit_code == 0, result.output
    push.assert_called_once()


def test_login_manifest_push_failure_is_nonfatal(runner, hat_cfg, mocker):
    backend = mocker.patch("hat.cli.load_backend").return_value
    backend.put.return_value = "ref://gh-token"
    mocker.patch("hat.cli.pull_manifest", return_value=None)
    mocker.patch("hat.cli.push_manifest", side_effect=RuntimeError("network down"))
    runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "github"],
        input="y\nmyuser\nghp_token123\nn\n",
    )
    assert result.exit_code == 0, result.output
    assert "could not sync config manifest" in result.output
    assert "network down" in result.output


def test_login_keychain_does_not_push_manifest(runner, hat_cfg, mocker):
    backend = mocker.patch("hat.cli.load_backend").return_value
    backend.put.return_value = "ref://gh-token"
    push = mocker.patch("hat.cli.push_manifest")
    runner.invoke(main, ["init"], input="3\nhat-\n")
    result = runner.invoke(
        main,
        ["login", "personal", "--service", "github"],
        input="y\nmyuser\nghp_token123\nn\n",
    )
    assert result.exit_code == 0, result.output
    push.assert_not_called()


def test_logout_pushes_manifest(runner, hat_cfg, mocker):
    backend = mocker.patch("hat.cli.load_backend").return_value
    backend.put.return_value = "ref://gh"
    mocker.patch("hat.cli.pull_manifest", return_value=None)
    push = mocker.patch("hat.cli.push_manifest")
    runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    runner.invoke(main, ["login", "personal", "--service", "github"],
                  input="y\nme\ntok\nn\n")
    push.reset_mock()
    result = runner.invoke(main, ["logout", "personal", "--service", "github"])
    assert result.exit_code == 0, result.output
    push.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_cli.py -k "manifest" -v`
Expected: FAIL — `AttributeError: <module 'hat.cli'> does not have the attribute 'push_manifest'`.

- [ ] **Step 3: Add imports, helper, and wire it in**

In `src/hat/cli.py`, add to the `from hat.config import (...)` block the name `Config` if not already imported (it is). Add a new import line after `from hat.env import build_env`:

```python
from hat.manifest import MANIFEST_SECRET_NAME, is_cloud_backend, pull_manifest, push_manifest
```

Add this helper immediately after the `_require_config` function:

```python
def _save_and_sync(cfg: Config, backend) -> None:
    save_config(cfg)
    if is_cloud_backend(cfg.secrets_backend):
        try:
            push_manifest(cfg, backend)
        except Exception as exc:
            click.echo(
                f"warning: could not sync config manifest ({exc}). "
                f"Run `hat push` later.",
                err=True,
            )


def _reject_reserved_secret_name(name: str) -> None:
    if name == MANIFEST_SECRET_NAME:
        raise click.ClickException(
            f"secret name {name!r} is reserved for the config manifest; "
            f"rename the profile or adjust secret_naming"
        )
```

In `login_cmd`, replace every occurrence of:

```python
        cfg.profiles[profile_name] = prof
        save_config(cfg)
```

with:

```python
        cfg.profiles[profile_name] = prof
        _save_and_sync(cfg, backend)
```

and the github branch's:

```python
            prof.github = gh
            cfg.profiles[profile_name] = prof
            save_config(cfg)
```

with:

```python
            prof.github = gh
            cfg.profiles[profile_name] = prof
            _save_and_sync(cfg, backend)
```

Add the reserved-name guard once, near the top of `login_cmd`, right after `backend = load_backend(cfg.secrets_backend)`:

```python
    _reject_reserved_secret_name(profile_name)
```

`_reject_reserved_secret_name` (defined above) raises only when the argument
equals `MANIFEST_SECRET_NAME`, so a profile literally named `hat-config-manifest`
is rejected. The default naming template (`hat-{profile}-{service}-{kind}`,
always ≥3 segments) cannot otherwise render to the 2-segment manifest name;
custom `secret_naming` templates that risk a collision are the user's
responsibility and are flagged in `references/schema.md` (Task 7).

In `logout_cmd`, replace its single:

```python
    save_config(cfg)
    click.echo(f"removed {service} from {profile_name}")
```

with:

```python
    _save_and_sync(cfg, backend)
    click.echo(f"removed {service} from {profile_name}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_cli.py -k "manifest or logout" -v`
Expected: PASS (the 4 new tests + existing `test_logout_removes_service`).

- [ ] **Step 5: Run the full CLI + unit suites for regressions**

Run: `uv run python -m pytest tests/test_cli.py tests/test_config.py tests/test_manifest.py tests/test_env.py -q`
Expected: PASS (no regressions).

- [ ] **Step 6: Commit**

```bash
git add src/hat/cli.py tests/test_cli.py
git commit -m "feat: auto-push config manifest on login/logout (non-fatal)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 4: `hat init` imports an existing manifest

**Files:**
- Modify: `src/hat/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def _manifest_cfg():
    from hat.config import (BackendConfig, Config, GitHubService, Profile,
                            SecretNaming)
    return Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="gcp_secret_manager", options={"project": "p1"}),
        bootstrap={"gcp_account": "me@x.com"},
        secret_naming=SecretNaming(default="hat-{profile}-{service}-{kind}",
                                   slack_token="hat-{profile}-slack-{workspace}-token"),
        profiles={"arinyaho": Profile(name="arinyaho",
                                       github=GitHubService(username="u", host="github.com",
                                                            token_ref="ref://x"))},
    )


def test_init_offers_and_imports_manifest(runner, hat_cfg, mocker):
    backend = mocker.patch("hat.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("hat.cli.subprocess.run")
    mocker.patch("hat.cli.pull_manifest", return_value=_manifest_cfg())
    result = runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
        input="y\n",
    )
    assert result.exit_code == 0, result.output
    assert "Imported 1 profiles" in result.output
    payload = json.loads(hat_cfg.read_text())
    assert "arinyaho" in payload["profiles"]


def test_init_no_import_flag_skips_manifest(runner, hat_cfg, mocker):
    backend = mocker.patch("hat.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("hat.cli.subprocess.run")
    mocker.patch("hat.cli.pull_manifest", return_value=_manifest_cfg())
    result = runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager", "--no-import",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(hat_cfg.read_text())
    assert payload["profiles"] == {}


def test_init_keychain_never_pulls_manifest(runner, hat_cfg, mocker):
    backend = mocker.patch("hat.cli.load_backend").return_value
    backend.health_check.return_value = None
    pull = mocker.patch("hat.cli.pull_manifest")
    result = runner.invoke(main, ["init"], input="3\nhat-\n")
    assert result.exit_code == 0, result.output
    pull.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_cli.py -k "init_offers or no_import or keychain_never" -v`
Expected: FAIL — `--no-import` is an unknown option / `pull_manifest` never called.

- [ ] **Step 3: Add `--no-import` option and the import block**

In `src/hat/cli.py`, add this option decorator to `init_cmd` (after the `--yes` option):

```python
@click.option("--no-import", "no_import", is_flag=True,
              help="Skip importing an existing config manifest from the backend.")
```

Add `no_import: bool` to the `init_cmd` signature (after `yes: bool`).

At the **end** of `init_cmd`, replace the final line:

```python
    click.echo("Next: `hat login <profile> --service google|github|slack`")
```

with:

```python
    if not no_import and is_cloud_backend(backend_cfg):
        try:
            remote = pull_manifest(backend)
        except Exception as exc:
            remote = None
            click.echo(f"(manifest check skipped: {exc})", err=True)
        if remote and remote.profiles:
            names = ", ".join(remote.profiles)
            do_import = yes or click.confirm(
                f"Found an existing hat config in this backend "
                f"({len(remote.profiles)} profiles: {names}). Import it?",
                default=True,
            )
            if do_import:
                save_config(remote)
                first = next(iter(remote.profiles))
                click.echo(
                    f'Imported {len(remote.profiles)} profiles. '
                    f'Try: eval "$(hat use {first})"'
                )
                return

    click.echo("Next: `hat login <profile> --service google|github|slack`")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_cli.py -k "init" -v`
Expected: PASS (new import tests + all existing `init` tests still green).

- [ ] **Step 5: Commit**

```bash
git add src/hat/cli.py tests/test_cli.py
git commit -m "feat: hat init imports existing config manifest (--no-import to skip)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 5: `hat sync` command

**Files:**
- Modify: `src/hat/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_sync_dry_run_reports_diff_and_writes_nothing(runner, hat_cfg, mocker):
    backend = mocker.patch("hat.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("hat.cli.subprocess.run")
    mocker.patch("hat.cli.pull_manifest", return_value=None)
    runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager", "--no-import",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    before = hat_cfg.read_text()
    mocker.patch("hat.cli.pull_manifest", return_value=_manifest_cfg())
    result = runner.invoke(main, ["sync", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "arinyaho" in result.output
    assert hat_cfg.read_text() == before  # unchanged


def test_sync_applies_with_yes(runner, hat_cfg, mocker):
    backend = mocker.patch("hat.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("hat.cli.subprocess.run")
    mocker.patch("hat.cli.pull_manifest", return_value=None)
    runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager", "--no-import",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    mocker.patch("hat.cli.pull_manifest", return_value=_manifest_cfg())
    result = runner.invoke(main, ["sync", "-y"])
    assert result.exit_code == 0, result.output
    payload = json.loads(hat_cfg.read_text())
    assert "arinyaho" in payload["profiles"]


def test_sync_no_manifest_errors(runner, hat_cfg, mocker):
    backend = mocker.patch("hat.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("hat.cli.subprocess.run")
    mocker.patch("hat.cli.pull_manifest", return_value=None)
    runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager", "--no-import",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    result = runner.invoke(main, ["sync"])
    assert result.exit_code != 0
    assert "no manifest" in result.output.lower()


def test_sync_requires_cloud_backend(runner, hat_cfg, mocker):
    backend = mocker.patch("hat.cli.load_backend").return_value
    backend.health_check.return_value = None
    runner.invoke(main, ["init"], input="3\nhat-\n")
    result = runner.invoke(main, ["sync"])
    assert result.exit_code != 0
    assert "cloud backend" in result.output.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_cli.py -k "sync" -v`
Expected: FAIL — `No such command 'sync'`.

- [ ] **Step 3: Add the `sync` command**

In `src/hat/cli.py`, add `from dataclasses import asdict` to the imports at the top (with the other stdlib imports). Add this command after `use_cmd`:

```python
def _profile_fingerprint(prof) -> str:
    return json.dumps(asdict(prof), sort_keys=True)


@main.command("sync")
@click.option("--dry-run", "dry_run", is_flag=True, help="Show what would change; write nothing.")
@click.option("--yes", "-y", is_flag=True, help="Apply without confirmation.")
def sync_cmd(dry_run: bool, yes: bool) -> None:
    """Pull the config manifest from the backend and reconcile local config."""
    cfg = _require_config()
    if not is_cloud_backend(cfg.secrets_backend):
        raise click.ClickException(
            "sync requires a cloud backend (gcp_secret_manager / oci_vault)"
        )
    backend = load_backend(cfg.secrets_backend)
    remote = pull_manifest(backend)
    if remote is None:
        raise click.ClickException("no manifest found in backend (nothing to sync)")

    local, rem = set(cfg.profiles), set(remote.profiles)
    added = sorted(rem - local)
    removed = sorted(local - rem)
    changed = sorted(
        n for n in local & rem
        if _profile_fingerprint(cfg.profiles[n]) != _profile_fingerprint(remote.profiles[n])
    )
    click.echo(f"+ add:    {', '.join(added) or '(none)'}")
    click.echo(f"- remove: {', '.join(removed) or '(none)'}")
    click.echo(f"~ change: {', '.join(changed) or '(none)'}")

    if dry_run:
        return
    if not (added or removed or changed):
        click.echo("already in sync")
        return
    if not yes:
        click.confirm("Replace local config with the manifest?", default=True, abort=True)
    save_config(remote)
    click.echo(f"synced {len(remote.profiles)} profiles from manifest")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_cli.py -k "sync" -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/hat/cli.py tests/test_cli.py
git commit -m "feat: hat sync — reconcile local config from backend manifest

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 6: `hat push` command

**Files:**
- Modify: `src/hat/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_push_command_pushes_manifest(runner, hat_cfg, mocker):
    backend = mocker.patch("hat.cli.load_backend").return_value
    backend.health_check.return_value = None
    mocker.patch("hat.cli.subprocess.run")
    mocker.patch("hat.cli.pull_manifest", return_value=None)
    runner.invoke(
        main,
        ["init", "--backend", "gcp_secret_manager", "--no-import",
         "--project", "p1", "--bootstrap-email", "me@x.com"],
    )
    push = mocker.patch("hat.cli.push_manifest")
    result = runner.invoke(main, ["push"])
    assert result.exit_code == 0, result.output
    push.assert_called_once()
    assert "pushed config manifest" in result.output


def test_push_command_noop_on_keychain(runner, hat_cfg, mocker):
    backend = mocker.patch("hat.cli.load_backend").return_value
    backend.health_check.return_value = None
    runner.invoke(main, ["init"], input="3\nhat-\n")
    push = mocker.patch("hat.cli.push_manifest")
    result = runner.invoke(main, ["push"])
    assert result.exit_code == 0, result.output
    push.assert_not_called()
    assert "no-op" in result.output.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_cli.py -k "push_command" -v`
Expected: FAIL — `No such command 'push'`.

- [ ] **Step 3: Add the `push` command**

In `src/hat/cli.py`, add this command after `sync_cmd`:

```python
@main.command("push")
def push_cmd() -> None:
    """Force-push the current local config to the backend manifest."""
    cfg = _require_config()
    if not is_cloud_backend(cfg.secrets_backend):
        click.echo("push is a no-op for local backends (macos_keychain)")
        return
    backend = load_backend(cfg.secrets_backend)
    push_manifest(cfg, backend)
    click.echo("pushed config manifest to backend")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_cli.py -k "push_command" -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the entire test suite**

Run: `uv run python -m pytest -q`
Expected: PASS (all suites; `test_backends_gcp.py` / `test_backends_oci.py` may still error on missing SDKs in a bare env — that is the pre-existing quirk, unrelated; they pass in CI).

- [ ] **Step 6: Commit**

```bash
git add src/hat/cli.py tests/test_cli.py
git commit -m "feat: hat push — manual config manifest upload (recovery path)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 7: Documentation

**Files:**
- Modify: `plugins/moza/skills/moza/references/schema.md`
- Modify: `plugins/moza/skills/moza/references/usage.md`

- [ ] **Step 1: Add the reserved-name note to schema.md**

Read `plugins/moza/skills/moza/references/schema.md`. Append this section at the end:

```markdown
## Reserved backend secret name

`hat-config-manifest` is reserved: `hat` stores a non-secret snapshot of
`config.json` (refs and identifiers only — no secret values) under this name in
cloud backends (`gcp_secret_manager`, `oci_vault`). It is pushed automatically
after every `hat login` / `hat logout`. Do not create a profile whose rendered
secret name collides with it.
```

- [ ] **Step 2: Add the cross-machine recipe to usage.md**

Read `plugins/moza/skills/moza/references/usage.md`. Append this section at the end:

```markdown
## Reuse on a second machine

Secrets already live in the cloud backend; the config manifest carries the
profile map. On the new machine:

```bash
gcloud auth application-default login --account=<bootstrap-email>
gcloud auth application-default set-quota-project <sm-project>
hat init --backend gcp_secret_manager --project <sm-project> \
  --bootstrap-email <bootstrap-email>
#   → "Found an existing hat config (N profiles: ...). Import it? [Y/n]"
eval "$(hat use <profile>)"
```

`hat init --no-import` skips the prompt. Later, re-pull with `hat sync`
(`--dry-run` to preview) or force-upload local state with `hat push`.
```

- [ ] **Step 3: Commit**

```bash
git add plugins/moza/skills/moza/references/schema.md plugins/moza/skills/moza/references/usage.md
git commit -m "docs: document config manifest reserved name + cross-machine reuse

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] Run `uv run python -m pytest tests/test_cli.py tests/test_config.py tests/test_manifest.py tests/test_env.py -q` — all green.
- [ ] `uv run hat sync --help`, `uv run hat push --help`, `uv run hat init --help` show the new commands/flags.
- [ ] Update `.claude-plugin/marketplace.json` `sha` to the new HEAD and push (per the repo's existing release habit), then the plugin install reflects the new docs.
