# moza ambient per-project env (`moza env sync`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a moza profile declare non-secret, per-directory env that `moza env sync` materializes into `~/.config/moza/ambient.zsh` (sourced by `~/.zshenv`), so any shell — including agent-harness non-interactive shells and git worktrees — that starts under a matching path gets the env for free.

**Architecture:** Add an optional `project_env` field to `Profile` (a list of `{match: cwd-glob, env: {K:V}}` scopes). A new `src/moza/ambient.py` renders all profiles' scopes into guarded `case "$PWD"` blocks and idempotently manages a marked region in `~/.zshenv`. A new `moza env sync` click command wires it together. Secrets are never emitted — the ambient file holds only references (e.g. `AWS_PROFILE=ccp`) and non-sensitive values; `build_env`/`use`/`exec` are untouched.

**Tech Stack:** Python 3.10+, click (already a dep), stdlib (`fnmatch`, `pathlib`, `dataclasses`). Tests: pytest + `monkeypatch`/`tmp_path`, click `CliRunner`. Run with `uv run pytest`.

## Global Constraints

- No new dependencies — click + stdlib only.
- **Secrets NEVER written to the ambient file.** Only `project_env` (non-secret) values: references (`AWS_PROFILE`), paths, region, secret-manager *names*. `build_env` (src/moza/env.py) is not modified.
- zsh only in v1; target `~/.zshenv`. Note the limitation in help/docs.
- Config `schema_version` stays `1` — `project_env` is additive with default `[]`, so pre-existing configs load unchanged (backward-compatible).
- Idempotent: `moza env sync` is re-runnable; the `~/.zshenv` region and the ambient file are regenerated wholesale, never duplicated.
- Paths honor the `MOZA_CONFIG` override: the ambient file sits beside the config file (`config_path().parent / "ambient.zsh"`).
- Match moza style: `from __future__ import annotations`, dataclasses, click commands under the `main` group, pytest tests in `tests/`.
- English only (source, comments, help text).
- Reused existing helpers (do NOT reimplement): `config.py` `Profile`, `config_path`, `serialize_config`/`deserialize_config`, `load_config`; `cli.py` `main` click group + `_require_config()`.

---

### Task 1: `project_env` config field

**Files:**
- Modify: `src/moza/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `ProjectEnvScope(match: str, env: dict[str, str])` dataclass; `Profile.project_env: list[ProjectEnvScope]` (default `[]`); round-trips through `serialize_config`/`deserialize_config`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
def test_project_env_round_trips():
    from moza.config import ProjectEnvScope
    cfg = Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={},
        secret_naming=SecretNaming(default="moza-{profile}-{service}-{kind}",
                                   slack_token="moza-{profile}-slack-{workspace}-token"),
        profiles={"ccp": Profile(
            name="ccp",
            project_env=[
                ProjectEnvScope(match="*/ccp/chemcopilot/*",
                                env={"AWS_PROFILE": "ccp", "CCP": "$HOME/ccp/chemcopilot"}),
                ProjectEnvScope(match="*/chemcopilot-ai*",
                                env={"PYTHONPATH": "$HOME/x/src"}),
            ],
        )},
    )
    back = deserialize_config(serialize_config(cfg))
    scopes = back.profiles["ccp"].project_env
    assert [s.match for s in scopes] == ["*/ccp/chemcopilot/*", "*/chemcopilot-ai*"]
    assert scopes[0].env["AWS_PROFILE"] == "ccp"
    assert scopes[1].env["PYTHONPATH"] == "$HOME/x/src"


def test_config_without_project_env_defaults_empty():
    raw = {
        "$schema_version": 1,
        "secrets_backend": {"type": "macos_keychain"},
        "bootstrap": {},
        "secret_naming": {"default": "d", "slack_token": "s"},
        "profiles": {"p": {"github": None}},
    }
    cfg = deserialize_config(raw)
    assert cfg.profiles["p"].project_env == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py::test_project_env_round_trips -v`
Expected: FAIL — `ImportError: cannot import name 'ProjectEnvScope'` (or `TypeError` on the `project_env=` kwarg).

- [ ] **Step 3: Implement**

In `src/moza/config.py`:

(a) Add the dataclass after `AtlassianService` (before `Profile`):

```python
@dataclass
class ProjectEnvScope:
    match: str
    env: dict[str, str] = field(default_factory=dict)
```

(b) Add the field to `Profile`:

```python
@dataclass
class Profile:
    name: str
    google: GoogleService | None = None
    github: GitHubService | None = None
    slack: list[SlackWorkspace] = field(default_factory=list)
    aws: AWSService | None = None
    oci: OCIService | None = None
    atlassian: AtlassianService | None = None
    project_env: list[ProjectEnvScope] = field(default_factory=list)
```

(c) In `_config_to_dict`, add `project_env` to the per-profile dict:

```python
        profiles[name] = {
            "google": asdict(prof.google) if prof.google else None,
            "github": asdict(prof.github) if prof.github else None,
            "slack": [asdict(w) for w in prof.slack],
            "aws": asdict(prof.aws) if prof.aws else None,
            "oci": asdict(prof.oci) if prof.oci else None,
            "atlassian": asdict(prof.atlassian) if prof.atlassian else None,
            "project_env": [asdict(s) for s in prof.project_env],
        }
```

(d) In `_config_from_dict`, parse it (default to empty when absent):

```python
        project_env = [
            ProjectEnvScope(match=s["match"], env=dict(s.get("env") or {}))
            for s in (p.get("project_env") or [])
        ]
        profiles[name] = Profile(
            name=name, google=google, github=github, slack=slack,
            aws=aws, oci=oci, atlassian=atlassian, project_env=project_env,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (new tests + all existing config tests).

- [ ] **Step 5: Commit**

```bash
git add src/moza/config.py tests/test_config.py
git commit -m "feat(config): add non-secret project_env scopes to Profile"
```

---

### Task 2: render ambient shell from scopes

**Files:**
- Create: `src/moza/ambient.py`
- Test: `tests/test_ambient.py`

**Interfaces:**
- Consumes: `Profile`, `ProjectEnvScope` from config.
- Produces: `render_ambient(profiles: dict[str, Profile]) -> str` — returns the full ambient script (managed header + one `case "$PWD"` block per scope, in declared order across profiles, sorted profiles by name for determinism).

- [ ] **Step 1: Write the failing test**

Create `tests/test_ambient.py`:

```python
from moza.ambient import render_ambient
from moza.config import Profile, ProjectEnvScope


def test_render_emits_guarded_case_blocks_in_order():
    profiles = {"ccp": Profile(name="ccp", project_env=[
        ProjectEnvScope(match="*/ccp/chemcopilot/*",
                        env={"AWS_PROFILE": "ccp", "CCP": "$HOME/ccp/chemcopilot"}),
        ProjectEnvScope(match="*/chemcopilot-ai*", env={"PYTHONPATH": "$HOME/x/src"}),
    ])}
    out = render_ambient(profiles)
    assert "# >>> moza ambient env" in out
    assert "# <<< moza ambient env" in out
    # broad scope first, narrow second
    i_broad = out.index('*/ccp/chemcopilot/*')
    i_narrow = out.index('*/chemcopilot-ai*')
    assert i_broad < i_narrow
    assert 'export AWS_PROFILE="ccp"' in out
    assert 'export CCP="$HOME/ccp/chemcopilot"' in out           # $HOME left for zsh to expand
    assert 'case "$PWD" in */ccp/chemcopilot/*)' in out


def test_render_escapes_quotes_and_backticks_but_keeps_dollar():
    profiles = {"p": Profile(name="p", project_env=[
        ProjectEnvScope(match="*/x/*", env={"Q": 'a"b`c', "V": "$HOME/y"}),
    ])}
    out = render_ambient(profiles)
    assert r'export Q="a\"b\`c"' in out
    assert 'export V="$HOME/y"' in out


def test_render_empty_when_no_scopes():
    out = render_ambient({"p": Profile(name="p")})
    assert "# >>> moza ambient env" in out       # header always present (managed marker)
    assert "case \"$PWD\"" not in out            # but no scope blocks
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ambient.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'moza.ambient'`.

- [ ] **Step 3: Implement**

Create `src/moza/ambient.py`:

```python
from __future__ import annotations

from moza.config import Profile

HEADER = "# >>> moza ambient env (generated — do not edit; run `moza env sync`) >>>"
FOOTER = "# <<< moza ambient env <<<"


def _emit_value(value: str) -> str:
    """Double-quote a value so zsh expands $HOME / $VAR, escaping only the
    characters that would break the string or inject a command. `$` is left
    intact intentionally (references like $HOME are the whole point); the
    config is the user's own non-secret file and is trusted for expansion."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`")
    return f'"{escaped}"'


def _scope_block(scope) -> str:
    lines = [f'case "$PWD" in {scope.match})']
    for key in scope.env:  # preserve declared order (dict is ordered)
        lines.append(f"  export {key}={_emit_value(scope.env[key])}")
    lines.append(";; esac")
    return "\n".join(lines)


def render_ambient(profiles: dict[str, Profile]) -> str:
    blocks = []
    for name in sorted(profiles):  # deterministic profile order
        for scope in profiles[name].project_env:
            blocks.append(_scope_block(scope))
    body = ("\n".join(blocks) + "\n") if blocks else ""
    return f"{HEADER}\n{body}{FOOTER}\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ambient.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/moza/ambient.py tests/test_ambient.py
git commit -m "feat(ambient): render non-secret project_env into guarded zsh case blocks"
```

---

### Task 3: ambient file path + write

**Files:**
- Modify: `src/moza/ambient.py`
- Test: `tests/test_ambient.py`

**Interfaces:**
- Consumes: `config_path` from config; `render_ambient`.
- Produces: `ambient_path() -> Path` (`config_path().parent / "ambient.zsh"`); `write_ambient(profiles) -> Path` (writes rendered content, returns the path).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ambient.py`:

```python
def test_ambient_path_beside_config(monkeypatch, tmp_path):
    monkeypatch.setenv("MOZA_CONFIG", str(tmp_path / "cfg.json"))
    from moza.ambient import ambient_path
    assert ambient_path() == tmp_path / "ambient.zsh"


def test_write_ambient_creates_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MOZA_CONFIG", str(tmp_path / "cfg.json"))
    from moza.ambient import write_ambient, ambient_path
    p = write_ambient({"p": Profile(name="p", project_env=[
        ProjectEnvScope(match="*/x/*", env={"K": "v"})])})
    assert p == ambient_path()
    text = p.read_text()
    assert 'export K="v"' in text
    assert "# >>> moza ambient env" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ambient.py::test_ambient_path_beside_config -v`
Expected: FAIL — `ImportError: cannot import name 'ambient_path'`.

- [ ] **Step 3: Implement**

In `src/moza/ambient.py` add (top imports and functions):

```python
from pathlib import Path

from moza.config import Profile, config_path
```

```python
def ambient_path() -> Path:
    return config_path().parent / "ambient.zsh"


def write_ambient(profiles: dict[str, Profile]) -> Path:
    path = ambient_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_ambient(profiles))
    return path
```

(Merge the `from moza.config import ...` line with the existing one — a single import statement.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ambient.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/moza/ambient.py tests/test_ambient.py
git commit -m "feat(ambient): ambient_path + write_ambient beside the config file"
```

---

### Task 4: idempotent `~/.zshenv` managed region

**Files:**
- Modify: `src/moza/ambient.py`
- Test: `tests/test_ambient.py`

**Interfaces:**
- Produces: `ensure_zshenv_sources(zshenv: Path, ambient: Path) -> bool` — idempotently inserts/updates a marked region that sources the ambient file; returns True if the file changed. Uses distinct region markers (`# >>> moza ambient (zshenv) >>>` … `# <<< moza ambient (zshenv) <<<`) so it is found/replaced wholesale, never duplicated.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ambient.py`:

```python
def test_ensure_zshenv_inserts_then_is_idempotent(tmp_path):
    from moza.ambient import ensure_zshenv_sources
    zshenv = tmp_path / ".zshenv"
    zshenv.write_text("# existing user content\nexport FOO=1\n")
    ambient = tmp_path / "ambient.zsh"

    changed1 = ensure_zshenv_sources(zshenv, ambient)
    body = zshenv.read_text()
    assert changed1 is True
    assert "# existing user content" in body            # preserved
    assert str(ambient) in body                          # sources the file
    assert body.count("moza ambient (zshenv)") == 2      # one begin + one end marker

    changed2 = ensure_zshenv_sources(zshenv, ambient)    # re-run
    assert changed2 is False                              # no change
    assert zshenv.read_text().count("moza ambient (zshenv)") == 2   # not duplicated


def test_ensure_zshenv_creates_file_when_absent(tmp_path):
    from moza.ambient import ensure_zshenv_sources
    zshenv = tmp_path / ".zshenv"
    ambient = tmp_path / "ambient.zsh"
    assert ensure_zshenv_sources(zshenv, ambient) is True
    assert str(ambient) in zshenv.read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ambient.py::test_ensure_zshenv_inserts_then_is_idempotent -v`
Expected: FAIL — `ImportError: cannot import name 'ensure_zshenv_sources'`.

- [ ] **Step 3: Implement**

In `src/moza/ambient.py` add:

```python
import re

ZSHENV_BEGIN = "# >>> moza ambient (zshenv) >>>"
ZSHENV_END = "# <<< moza ambient (zshenv) <<<"


def _zshenv_region(ambient: Path) -> str:
    return (
        f'{ZSHENV_BEGIN}\n'
        f'[ -f "{ambient}" ] && source "{ambient}"\n'
        f'{ZSHENV_END}'
    )


def ensure_zshenv_sources(zshenv: Path, ambient: Path) -> bool:
    region = _zshenv_region(ambient)
    old = zshenv.read_text() if zshenv.exists() else ""
    pattern = re.compile(
        re.escape(ZSHENV_BEGIN) + r".*?" + re.escape(ZSHENV_END),
        re.DOTALL,
    )
    if pattern.search(old):
        new = pattern.sub(lambda _m: region, old)
    else:
        sep = "" if old == "" or old.endswith("\n") else "\n"
        new = f"{old}{sep}{region}\n"
    if new == old:
        return False
    zshenv.parent.mkdir(parents=True, exist_ok=True)
    zshenv.write_text(new)
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ambient.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/moza/ambient.py tests/test_ambient.py
git commit -m "feat(ambient): idempotent ~/.zshenv managed region"
```

---

### Task 5: `moza env sync` command + docs

**Files:**
- Modify: `src/moza/cli.py`
- Modify: `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `write_ambient`, `ambient_path`, `ensure_zshenv_sources` from ambient; `_require_config` and the `main` click group from cli.
- Produces: `moza env sync` — writes the ambient file, wires `~/.zshenv`, prints a summary (scope count per profile + the two paths).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py` (follow the file's existing `CliRunner` usage; import `main` from `moza.cli` and set `MOZA_CONFIG` to a tmp config that has a `project_env` scope):

```python
def test_env_sync_writes_ambient_and_wires_zshenv(monkeypatch, tmp_path):
    from click.testing import CliRunner
    from moza.cli import main
    from moza.config import (Config, BackendConfig, SecretNaming, Profile,
                             ProjectEnvScope, save_config)
    monkeypatch.setenv("MOZA_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("HOME", str(tmp_path))       # so ~/.zshenv resolves under tmp
    save_config(Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={},
        secret_naming=SecretNaming(default="d", slack_token="s"),
        profiles={"ccp": Profile(name="ccp", project_env=[
            ProjectEnvScope(match="*/ccp/*", env={"AWS_PROFILE": "ccp"})])},
    ))
    res = CliRunner().invoke(main, ["env", "sync"])
    assert res.exit_code == 0, res.output
    ambient = (tmp_path / "config.json").parent / "ambient.zsh"
    assert 'export AWS_PROFILE="ccp"' in ambient.read_text()
    assert str(ambient) in (tmp_path / ".zshenv").read_text()
    assert "ccp" in res.output and "1" in res.output      # summary mentions the profile + scope count
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_env_sync_writes_ambient_and_wires_zshenv -v`
Expected: FAIL — click reports "No such command 'env'".

- [ ] **Step 3: Implement**

In `src/moza/cli.py`:

(a) Add imports (merge with existing import blocks):

```python
from pathlib import Path
from moza.ambient import write_ambient, ambient_path, ensure_zshenv_sources
```

(b) Add the command group + subcommand (place near the other `@main.command` definitions):

```python
@main.group("env")
def env_group() -> None:
    """Manage ambient per-project env (zsh only)."""


@env_group.command("sync")
def env_sync_cmd() -> None:
    """Generate the ambient env file from every profile's project_env and
    ensure ~/.zshenv sources it. Non-secret only; re-runnable (idempotent)."""
    cfg = _require_config()
    ambient = write_ambient(cfg.profiles)
    zshenv = Path(os.environ.get("HOME", str(Path.home()))) / ".zshenv"
    changed = ensure_zshenv_sources(zshenv, ambient)
    total = 0
    for name in sorted(cfg.profiles):
        n = len(cfg.profiles[name].project_env)
        if n:
            click.echo(f"  {name}: {n} scope(s)")
            total += n
    click.echo(f"Wrote {total} scope(s) to {ambient}")
    click.echo(f"~/.zshenv {'updated' if changed else 'already wired'}: {zshenv}")
    if total == 0:
        click.echo("No project_env scopes configured. Add them under a profile's "
                   "project_env, then re-run. (zsh only in v1.)")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::test_env_sync_writes_ambient_and_wires_zshenv -v`
Expected: PASS.

- [ ] **Step 5: Update README**

Add a short section to `README.md` documenting `moza env sync`: what it does (materialize non-secret per-project env into `~/.config/moza/ambient.zsh`, sourced by `~/.zshenv`), the non-secret invariant, the zsh-only v1 limitation, and a `project_env` config example. Keep it to ~15 lines.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS (all suites, including the new ambient + config + cli tests).

- [ ] **Step 7: Commit**

```bash
git add src/moza/cli.py tests/test_cli.py README.md
git commit -m "feat(cli): moza env sync — materialize ambient per-project env"
```

---

## Self-Review

**Spec coverage (against the handoff issue `docs/ambient-project-env.issue.md`):**
- `project_env` profile config (issue §1): Task 1. ✓
- `moza env sync` command (issue §2): Task 5. ✓
- `~/.zshenv` integration / managed region (issue §3): Task 4. ✓
- Generation semantics — independent guarded `case "$PWD"` blocks, broad→narrow order, `$HOME`/prior-var expansion (issue §4): Task 2. ✓
- Non-goal "secrets stay dynamic" — ambient reads only `project_env`; `build_env`/`use`/`exec` untouched: enforced by construction (no task touches env.py/shell.py secret paths). ✓
- Non-goal "zsh only v1" — targets `~/.zshenv`; limitation noted in help + README. ✓

**Placeholder scan:** none — every code + test step is complete; commands and expected results are explicit.

**Type consistency:** `render_ambient(profiles: dict[str,Profile]) -> str` (T2) consumed by `write_ambient` (T3); `ambient_path()`/`write_ambient()`/`ensure_zshenv_sources(zshenv, ambient)` (T3/T4) consumed by `env_sync_cmd` (T5); `ProjectEnvScope(match, env)` (T1) used across T2–T5. Consistent.

## Notes for the executor

- Work in a git worktree off moza `main` (`superpowers:using-git-worktrees`), branch e.g. `feat/ambient-env`. Push/PR as the `arinyaho` identity (`moza exec arinyaho -- git push` / `gh`).
- Tests: `uv run pytest` provisions the worktree's env from `uv.lock`; if a worktree run reports missing deps, run `uv sync` once in the worktree first.
- The handoff issue stays LOCAL (moza deletes specs/plans from the repo — see commit a0f1ecb); do not commit `docs/ambient-project-env.issue.md` or this plan into the repo.
- `MOZA_CONFIG` override points config + ambient at a tmp dir in tests; production paths are `~/.config/moza/{config.json,ambient.zsh}`.
- Deferred (not v1): auto-running `env sync` on config mutations (`_save_and_sync`); bash/fish ports; a `moza env status`/`--check` subcommand.
