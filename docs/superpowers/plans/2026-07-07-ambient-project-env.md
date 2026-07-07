# moza ambient per-project env (`moza env sync`) Implementation Plan (v2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a moza profile declare non-secret, per-directory env that `moza env sync` materializes into `~/.config/moza/ambient.zsh` (sourced by `~/.zshenv`), so any non-interactive **zsh** — including agent-harness shells and git worktrees under a matching path — gets the env for free.

**Architecture:** Add an optional `project_env` field to `Profile` (a list of `{match: cwd-glob, env: {K:V}}` scopes). A new `src/moza/ambient.py` renders all profiles' scopes into guarded `case "$PWD/" in …` blocks and idempotently manages a marked region in `~/.zshenv`. A new `moza env sync` click command renders, **parse-validates the generated script with `zsh -n` before touching the filesystem**, then writes and wires it. Secrets are never emitted; `build_env`/`use`/`exec` are untouched.

**Tech Stack:** Python 3.10+, click (existing dep), stdlib (`subprocess`, `shutil`, `pathlib`, `dataclasses`). Tests: pytest + `monkeypatch`/`tmp_path`, click `CliRunner`, plus a real-`zsh` behavioral test (skipped when zsh is absent). Run with `uv run pytest`.

## Global Constraints

- No new dependencies — click + stdlib only.
- **Secrets NEVER written to the ambient file.** Only `project_env` (non-secret) values. `build_env` (src/moza/env.py) is not modified.
- **Coverage boundary (do not overclaim):** `~/.zshenv` is sourced by non-interactive **zsh** only. `/bin/sh -c`, `bash -c`, and `Python subprocess(shell=True)` (which uses `/bin/sh`) do NOT source it and get nothing. The Claude Code Bash tool runs zsh here, so it is covered — that is harness-specific, not universal. State this in help/README; do not claim "all non-interactive shells".
- **Generated file is executable zsh.** Values are emitted double-quoted so zsh expands `$HOME`/prior vars — which also means `$(...)`, `${...}`, and backticks in a value are evaluated. The config is the user's own non-secret file and is trusted for this. Safety against *breakage* is the `zsh -n` parse-gate (below), NOT value escaping; escaping only preserves string-literal integrity.
- **Parse-gate invariant:** `moza env sync` MUST `zsh -n`-validate the rendered script and abort — leaving `ambient.zsh` and `~/.zshenv` untouched — if it does not parse. A malformed value must never reach a live, sourced-by-every-zsh file.
- Config `schema_version` stays `1` — `project_env` is additive with default `[]` (backward-compatible).
- Idempotent: `moza env sync` re-runnable; ambient file and `~/.zshenv` region regenerated wholesale, never duplicated.
- Paths honor `MOZA_CONFIG`: the ambient file sits beside the config (`config_path().parent / "ambient.zsh"`).
- Match moza style: `from __future__ import annotations`, dataclasses, click commands under the `main` group, pytest tests in `tests/`.
- English only.
- Reused (do NOT reimplement): `config.py` `Profile`/`config_path`/`serialize_config`/`deserialize_config`/`load_config`; `cli.py` `main` group, `_require_config()`, and `MozaGroup` (the group class `main` uses).

---

### Task 1: `project_env` config field

**Files:**
- Modify: `src/moza/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `ProjectEnvScope(match: str, env: dict[str, str])`; `Profile.project_env: list[ProjectEnvScope]` (default `[]`); round-trips through serialize/deserialize.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
def test_project_env_round_trips():
    from moza.config import ProjectEnvScope
    cfg = Config(
        schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={},
        secret_naming=SecretNaming(default="d", slack_token="s"),
        profiles={"ccp": Profile(name="ccp", project_env=[
            ProjectEnvScope(match="*/ccp/chemcopilot", env={"AWS_PROFILE": "ccp", "CCP": "$HOME/ccp/chemcopilot"}),
            ProjectEnvScope(match="*/chemcopilot-ai*", env={"PYTHONPATH": "$HOME/x/src"}),
        ])},
    )
    back = deserialize_config(serialize_config(cfg))
    scopes = back.profiles["ccp"].project_env
    assert [s.match for s in scopes] == ["*/ccp/chemcopilot", "*/chemcopilot-ai*"]
    assert scopes[0].env["AWS_PROFILE"] == "ccp"


def test_config_without_project_env_defaults_empty():
    raw = {"$schema_version": 1, "secrets_backend": {"type": "macos_keychain"},
           "bootstrap": {}, "secret_naming": {"default": "d", "slack_token": "s"},
           "profiles": {"p": {"github": None}}}
    assert deserialize_config(raw).profiles["p"].project_env == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py::test_project_env_round_trips -v`
Expected: FAIL — `ImportError: cannot import name 'ProjectEnvScope'`.

- [ ] **Step 3: Implement**

In `src/moza/config.py`:

(a) Add after `AtlassianService`:

```python
@dataclass
class ProjectEnvScope:
    match: str
    env: dict[str, str] = field(default_factory=dict)
```

(b) Add the field to `Profile` (last field):

```python
    project_env: list[ProjectEnvScope] = field(default_factory=list)
```

(c) In `_config_to_dict`, add to the per-profile dict:

```python
            "project_env": [asdict(s) for s in prof.project_env],
```

(d) In `_config_from_dict`, before building `Profile`:

```python
        project_env = [
            ProjectEnvScope(match=s["match"], env=dict(s.get("env") or {}))
            for s in (p.get("project_env") or [])
        ]
```

and pass `project_env=project_env` to the `Profile(...)` constructor.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/moza/config.py tests/test_config.py
git commit -m "feat(config): add non-secret project_env scopes to Profile"
```

---

### Task 2: render ambient shell from scopes (honest emission + root-inclusive glob)

**Files:**
- Create: `src/moza/ambient.py`
- Test: `tests/test_ambient.py`

**Interfaces:**
- Produces: `render_ambient(profiles: dict[str, Profile]) -> str`. Each scope becomes `case "$PWD/" in <base>/*) … ;; esac`, where `<base>` is `match` with a trailing `/*` or `/` stripped — so a scope matches its directory ROOT and everything under it (the root-miss bug is fixed here). Values are double-quoted, escaping only `\` and `"` (string integrity); `$` and backticks are left for zsh to evaluate.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ambient.py`:

```python
from moza.ambient import render_ambient
from moza.config import Profile, ProjectEnvScope


def test_render_matches_root_and_subdirs():
    profiles = {"ccp": Profile(name="ccp", project_env=[
        ProjectEnvScope(match="*/ccp/chemcopilot", env={"AWS_PROFILE": "ccp", "CCP": "$HOME/ccp/chemcopilot"}),
    ])}
    out = render_ambient(profiles)
    # matches on "$PWD/" so the directory root itself is covered, not just subdirs
    assert 'case "$PWD/" in */ccp/chemcopilot/*)' in out
    assert 'export AWS_PROFILE="ccp"' in out
    assert 'export CCP="$HOME/ccp/chemcopilot"' in out       # $HOME left for zsh


def test_render_trailing_glob_is_normalized():
    # a user who writes the old "/*"-style glob gets the same base
    profiles = {"p": Profile(name="p", project_env=[
        ProjectEnvScope(match="*/ccp/chemcopilot/*", env={"K": "v"})])}
    assert 'case "$PWD/" in */ccp/chemcopilot/*)' in render_ambient(profiles)


def test_render_escapes_only_quote_and_backslash_keeps_dollar_and_backtick():
    profiles = {"p": Profile(name="p", project_env=[
        ProjectEnvScope(match="*/x", env={"Q": 'a"b\\c', "V": "$HOME/y", "B": "x`y"})])}
    out = render_ambient(profiles)
    assert r'export Q="a\"b\\c"' in out       # " and \ escaped for string integrity
    assert 'export V="$HOME/y"' in out        # $ kept (feature)
    assert 'export B="x`y"' in out            # backtick NOT escaped — honestly eval'd


def test_render_empty_when_no_scopes():
    out = render_ambient({"p": Profile(name="p")})
    assert "# >>> moza ambient env" in out
    assert 'case "$PWD/"' not in out
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
    """Double-quote so zsh expands $HOME / $VAR. Escape only backslash and
    double-quote — the minimum for a well-formed string literal. `$` and
    backticks are intentionally left intact: the value IS evaluated by zsh
    (that is how references work). The config is trusted; `env sync`'s
    `zsh -n` parse-gate guards against a value that breaks syntax."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _match_base(match: str) -> str:
    """Directory-root glob: strip a trailing '/*' or '/' so the scope matches
    the directory itself AND everything under it when tested against "$PWD/"."""
    base = match
    if base.endswith("/*"):
        base = base[:-2]
    return base.rstrip("/")


def _scope_block(scope) -> str:
    lines = [f'case "$PWD/" in {_match_base(scope.match)}/*)']
    for key in scope.env:  # preserve declared key order
        lines.append(f"  export {key}={_emit_value(scope.env[key])}")
    lines.append(";; esac")
    return "\n".join(lines)


def render_ambient(profiles: dict[str, Profile]) -> str:
    blocks = []
    for name in sorted(profiles):  # deterministic; see plan note on cross-profile order
        for scope in profiles[name].project_env:
            blocks.append(_scope_block(scope))
    body = ("\n".join(blocks) + "\n") if blocks else ""
    return f"{HEADER}\n{body}{FOOTER}\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ambient.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/moza/ambient.py tests/test_ambient.py
git commit -m "feat(ambient): render project_env into root-inclusive guarded zsh blocks"
```

---

### Task 3: ambient path, write, and `zsh -n` parse-gate

**Files:**
- Modify: `src/moza/ambient.py`
- Test: `tests/test_ambient.py`

**Interfaces:**
- Consumes: `config_path` from config; `render_ambient`.
- Produces: `ambient_path() -> Path`; `assert_parses(script: str) -> None` (raises `AmbientParseError` if `zsh -n` rejects the script; a no-op that returns cleanly if zsh is unavailable, since the gate can only run where zsh exists); `write_ambient(profiles) -> Path` (renders, **parse-validates**, then writes — never writes an unparseable script).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ambient.py`:

```python
import shutil
import pytest
from moza.ambient import ambient_path, write_ambient, assert_parses, AmbientParseError


def test_ambient_path_beside_config(monkeypatch, tmp_path):
    monkeypatch.setenv("MOZA_CONFIG", str(tmp_path / "cfg.json"))
    assert ambient_path() == tmp_path / "ambient.zsh"


@pytest.mark.skipif(not shutil.which("zsh"), reason="zsh required")
def test_assert_parses_rejects_broken_script():
    assert_parses('case "$PWD/" in */x/*)\n  export K="ok"\n;; esac\n')  # ok
    with pytest.raises(AmbientParseError):
        assert_parses('case "$PWD/" in */x/*)\n  export K="unterminated\n')  # broken


@pytest.mark.skipif(not shutil.which("zsh"), reason="zsh required")
def test_write_ambient_refuses_unparseable(monkeypatch, tmp_path):
    monkeypatch.setenv("MOZA_CONFIG", str(tmp_path / "cfg.json"))
    # _emit_value escapes \ and ", and a newline inside "..." is legal zsh, so
    # almost every value renders as a well-formed literal. The gate's real job is
    # the one thing left raw: an unbalanced command-substitution open ("$(") — that
    # is what `zsh -n` rejects, so write_ambient must refuse it.
    bad = Profile(name="p", project_env=[ProjectEnvScope(match="*/x", env={"K": "$("})])
    with pytest.raises(AmbientParseError):
        write_ambient({"p": bad})
    assert not ambient_path().exists()      # nothing written on failure


def test_write_ambient_creates_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MOZA_CONFIG", str(tmp_path / "cfg.json"))
    p = write_ambient({"p": Profile(name="p", project_env=[
        ProjectEnvScope(match="*/x", env={"K": "v"})])})
    assert p == ambient_path()
    assert 'export K="v"' in p.read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ambient.py::test_write_ambient_creates_file -v`
Expected: FAIL — `ImportError: cannot import name 'ambient_path'`.

- [ ] **Step 3: Implement**

In `src/moza/ambient.py` add imports and functions:

```python
import shutil
import subprocess
from pathlib import Path

from moza.config import Profile, config_path


class AmbientParseError(Exception):
    pass


def ambient_path() -> Path:
    return config_path().parent / "ambient.zsh"


def assert_parses(script: str) -> None:
    """Reject a script that zsh cannot parse. `zsh -n` parses without executing.
    If zsh is not installed, skip the check (it can only run where zsh runs)."""
    zsh = shutil.which("zsh")
    if not zsh:
        return
    proc = subprocess.run([zsh, "-n"], input=script, text=True, capture_output=True)
    if proc.returncode != 0:
        raise AmbientParseError(proc.stderr.strip() or "zsh -n rejected the ambient script")


def write_ambient(profiles: dict[str, Profile]) -> Path:
    script = render_ambient(profiles)
    assert_parses(script)               # never write an unparseable file
    path = ambient_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(script)
    return path
```

(Merge the `from moza.config import ...` with the existing import line.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ambient.py -v`
Expected: PASS (zsh-gated tests skip if zsh absent).

- [ ] **Step 5: Commit**

```bash
git add src/moza/ambient.py tests/test_ambient.py
git commit -m "feat(ambient): parse-gate (zsh -n) before writing the ambient file"
```

---

### Task 4: idempotent `~/.zshenv` managed region + behavioral test

**Files:**
- Modify: `src/moza/ambient.py`
- Test: `tests/test_ambient.py`

**Interfaces:**
- Produces: `ensure_zshenv_sources(zshenv: Path, ambient: Path) -> bool` — idempotently inserts/replaces a marked region sourcing `ambient`; returns True if the file changed.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ambient.py`:

```python
def test_ensure_zshenv_inserts_then_idempotent(tmp_path):
    from moza.ambient import ensure_zshenv_sources
    zshenv = tmp_path / ".zshenv"
    zshenv.write_text("# user content\nexport FOO=1\n")
    ambient = tmp_path / "ambient.zsh"
    assert ensure_zshenv_sources(zshenv, ambient) is True
    body = zshenv.read_text()
    assert "# user content" in body and str(ambient) in body
    assert body.count("moza ambient (zshenv)") == 2
    assert ensure_zshenv_sources(zshenv, ambient) is False       # re-run: no change
    assert zshenv.read_text().count("moza ambient (zshenv)") == 2


@pytest.mark.skipif(not shutil.which("zsh"), reason="zsh required")
def test_behavioral_ambient_applies_under_matching_pwd(monkeypatch, tmp_path):
    # End-to-end: a real zsh, cd'd into a matching dir, sourcing ambient.zsh,
    # actually exports the value. This is the only test that proves it WORKS.
    monkeypatch.setenv("MOZA_CONFIG", str(tmp_path / "cfg.json"))
    matchdir = tmp_path / "proj" / "ccp" / "chemcopilot"
    matchdir.mkdir(parents=True)
    write_ambient({"p": Profile(name="p", project_env=[
        ProjectEnvScope(match="*/ccp/chemcopilot", env={"AWS_PROFILE": "ccp"})])})
    amb = ambient_path()
    script = f'cd "{matchdir}"; source "{amb}"; print -r -- "$AWS_PROFILE"'
    out = subprocess.run(["zsh", "-fc", script], text=True, capture_output=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ccp"        # value applied at the directory root
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ambient.py::test_ensure_zshenv_inserts_then_idempotent -v`
Expected: FAIL — `ImportError: cannot import name 'ensure_zshenv_sources'`.

- [ ] **Step 3: Implement**

In `src/moza/ambient.py` add:

```python
import re

ZSHENV_BEGIN = "# >>> moza ambient (zshenv) >>>"
ZSHENV_END = "# <<< moza ambient (zshenv) <<<"


def ensure_zshenv_sources(zshenv: Path, ambient: Path) -> bool:
    region = (
        f'{ZSHENV_BEGIN}\n[ -f "{ambient}" ] && source "{ambient}"\n{ZSHENV_END}'
    )
    old = zshenv.read_text() if zshenv.exists() else ""
    pattern = re.compile(re.escape(ZSHENV_BEGIN) + r".*?" + re.escape(ZSHENV_END), re.DOTALL)
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
Expected: PASS (behavioral test runs where zsh exists, else skips).

- [ ] **Step 5: Commit**

```bash
git add src/moza/ambient.py tests/test_ambient.py
git commit -m "feat(ambient): idempotent ~/.zshenv region + real-zsh behavioral test"
```

---

### Task 5: `moza env sync` command + docs

**Files:**
- Modify: `src/moza/cli.py`
- Modify: `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `write_ambient`, `ambient_path`, `ensure_zshenv_sources`, `AmbientParseError` from ambient; `_require_config`, `main`, `MozaGroup` from cli.
- Produces: `moza env sync` — render → parse-gate (via `write_ambient`) → wire `~/.zshenv` → summary. Aborts cleanly (nonzero, nothing wired) if the generated script fails to parse.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py` (match the file's existing `CliRunner` usage):

```python
def test_env_sync_writes_ambient_and_wires_zshenv(monkeypatch, tmp_path):
    from click.testing import CliRunner
    from moza.cli import main
    from moza.config import (Config, BackendConfig, SecretNaming, Profile,
                             ProjectEnvScope, save_config)
    monkeypatch.setenv("MOZA_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("HOME", str(tmp_path))
    save_config(Config(schema_version=1,
        secrets_backend=BackendConfig(type="macos_keychain", options={}),
        bootstrap={}, secret_naming=SecretNaming(default="d", slack_token="s"),
        profiles={"ccp": Profile(name="ccp", project_env=[
            ProjectEnvScope(match="*/ccp", env={"AWS_PROFILE": "ccp"})])}))
    res = CliRunner().invoke(main, ["env", "sync"])
    assert res.exit_code == 0, res.output
    ambient = (tmp_path / "config.json").parent / "ambient.zsh"
    assert 'export AWS_PROFILE="ccp"' in ambient.read_text()
    assert str(ambient) in (tmp_path / ".zshenv").read_text()
    assert "ccp" in res.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_env_sync_writes_ambient_and_wires_zshenv -v`
Expected: FAIL — click reports "No such command 'env'".

- [ ] **Step 3: Implement**

In `src/moza/cli.py`:

(a) Add imports (merge with existing blocks):

```python
from pathlib import Path
from moza.ambient import write_ambient, ambient_path, ensure_zshenv_sources, AmbientParseError
```

(b) Add the group + command. Use `cls=MozaGroup` so the subgroup inherits the same behavior as `main` (which is `@click.group(cls=MozaGroup)`):

```python
@main.group("env", cls=MozaGroup)
def env_group() -> None:
    """Manage ambient per-project env (non-interactive zsh only)."""


@env_group.command("sync")
def env_sync_cmd() -> None:
    """Generate ~/.config/moza/ambient.zsh from every profile's project_env and
    ensure ~/.zshenv sources it. Non-secret only. Idempotent. The generated
    script is `zsh -n`-validated before anything is written or wired."""
    cfg = _require_config()
    try:
        ambient = write_ambient(cfg.profiles)          # renders + parse-gates + writes
    except AmbientParseError as exc:
        raise click.ClickException(
            f"Generated ambient script does not parse; nothing written.\n{exc}\n"
            "Check your project_env values (unbalanced quotes, stray newlines)."
        )
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
                   "project_env and re-run. (Non-interactive zsh only in v1.)")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::test_env_sync_writes_ambient_and_wires_zshenv -v`
Expected: PASS.

- [ ] **Step 5: Update README**

Add a ~15-line section documenting `moza env sync`: what it materializes; the non-secret invariant; the **coverage boundary** (non-interactive zsh only — not `/bin/sh`/`bash -c`); the `zsh -n` parse-gate; a `project_env` config example using a bare directory glob (`match = "*/ccp/chemcopilot"`, not `.../*`); and a note that a scope only covers a git worktree if the worktree's path is under the scope's glob (worktrees created in a sibling `/worktrees/` dir outside the glob are NOT covered).

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS (all suites).

- [ ] **Step 7: Commit**

```bash
git add src/moza/cli.py tests/test_cli.py README.md
git commit -m "feat(cli): moza env sync — parse-gated ambient per-project env"
```

---

## Self-Review

**Spec coverage (handoff issue + review findings):**
- `project_env` config (issue §1): Task 1. ✓
- render / generation semantics — guarded blocks, `$HOME` expansion, order (issue §4): Task 2. ✓
- **Root-inclusive glob (review #3):** Task 2 `_match_base` + `case "$PWD/"`. ✓
- **Honest value emission (review #2):** Task 2 `_emit_value` escapes only `\`/`"`; docstring states values are eval'd. ✓
- **Parse-gate (review #1, HIGH):** Task 3 `assert_parses` + `write_ambient`; Task 5 aborts on `AmbientParseError`. ✓
- **Behavioral test (review #4):** Task 4 real-zsh source + `print $AWS_PROFILE`; Task 3 rejects-unparseable test. ✓
- `~/.zshenv` region (issue §3): Task 4. ✓
- `moza env sync` (issue §2): Task 5. ✓
- **Coverage boundary (review #5):** Global Constraints + README (non-interactive zsh only). ✓
- **MozaGroup subgroup (review #8):** Task 5 `cls=MozaGroup`. ✓
- Non-goal "secrets stay dynamic": no task touches env.py/shell.py secret paths. ✓

**Placeholder scan:** none.

**Type consistency:** `render_ambient(dict[str,Profile])->str` (T2) → `write_ambient` (T3); `assert_parses(str)->None` raising `AmbientParseError` (T3) → caught in `env_sync_cmd` (T5); `ambient_path()`/`ensure_zshenv_sources(zshenv, ambient)` (T3/T4) → T5. Consistent.

## Notes for the executor

- Work in a git worktree off moza `main` (`superpowers:using-git-worktrees`), branch `feat/ambient-env`. Push/PR as `arinyaho` (`moza exec arinyaho -- …`).
- Tests: `uv run pytest`. The zsh-gated tests (`assert_parses`, behavioral, parse-refusal) skip where zsh is absent — but this is the load-bearing safety, so run them somewhere zsh exists before merge.
- The handoff issue + this plan stay LOCAL (moza deletes specs/plans from the repo — commit a0f1ecb). Do not commit them.
- **Review notes carried as documented boundaries, not code (accepted as low-severity):**
  - #6 cross-profile order is alphabetical (by profile name), so broad→narrow specificity holds only *within* a profile; two profiles with overlapping `match` → the alphabetically-last profile wins. Fine when project paths are disjoint (the normal case). Revisit with match-length (specificity) global sort only if it bites.
  - #7 a scope covers a worktree only if the worktree path is under the scope glob; document the worktree-root convention in the config example so the headline use-case isn't silently missed.
- Deferred (not v1): auto-`env sync` on config mutation (`_save_and_sync`); bash/fish ports; `moza env status`/`--check`.
