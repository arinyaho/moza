from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import click

from moza.ambient import (
    AmbientParseError,
    ensure_zshenv_sources,
    unexpandable_scope_vars,
    write_ambient,
)
from moza.backends import load_backend
from moza.ephemeral import EphemeralStore
from moza.config import (
    AWSService,
    AtlassianService,
    BackendConfig,
    Config,
    GitHubService,
    GoogleService,
    NotionService,
    OCIService,
    Profile,
    SecretNaming,
    SlackWorkspace,
    config_path,
    load_config,
    save_config,
)
from moza.env import build_env
from moza.manifest import MANIFEST_SECRET_NAME, is_cloud_backend, pull_manifest, push_manifest
from moza.oauth import exchange_refresh_token, google_installed_app_flow
from moza.resolve import AmbiguousScope, resolve_profile
from moza.verify import Status, probe_aws, probe_github, probe_google
from moza.secret_naming import render_name
from moza.shell import emit_unset, emit_use


GOOGLE_DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/cloud-platform",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]


def _friendly_backend_message(exc: BaseException) -> str | None:
    """Translate noisy backend exceptions to actionable hints."""
    try:
        from google.api_core import exceptions as gerr
    except ImportError:
        gerr = None  # type: ignore[assignment]

    cfg = load_config()
    project = "<project>"
    account = "<bootstrap-email>"
    if cfg:
        project = cfg.secrets_backend.options.get("project", project)
        account = (cfg.bootstrap or {}).get("gcp_account", account)

    if gerr is not None and isinstance(exc, gerr.PermissionDenied):
        return (
            f"Permission denied accessing Secret Manager (project {project!r}).\n\n"
            "Most likely cause: your Application Default Credentials (ADC) is signed\n"
            "in as a different account than the moza bootstrap account.\n\n"
            "Check the current ADC account:\n"
            "  TOKEN=$(gcloud auth application-default print-access-token)\n"
            '  curl -s "https://oauth2.googleapis.com/tokeninfo?access_token=$TOKEN" | jq .email\n\n'
            f"If it isn't {account!r}, fix it:\n"
            f"  gcloud auth application-default login --account={account}\n\n"
            "Then verify with: moza doctor"
        )
    if gerr is not None and isinstance(exc, gerr.Unauthenticated):
        return (
            "No Application Default Credentials available.\n\n"
            f"  gcloud auth application-default login --account={account}\n\n"
            "Then verify with: moza doctor"
        )
    return None


class MozaGroup(click.Group):
    def invoke(self, ctx: click.Context):
        try:
            return super().invoke(ctx)
        except click.ClickException:
            raise
        except Exception as exc:
            msg = _friendly_backend_message(exc)
            if msg:
                raise click.ClickException(msg) from exc
            raise


@click.group(cls=MozaGroup)
@click.version_option(package_name="moza")
def main() -> None:
    """moza — multi-identity credential router."""
    # moza's own backend access always uses the bootstrap ADC.
    # An active profile's GOOGLE_APPLICATION_CREDENTIALS is meant for downstream
    # programs (gcloud, gh, etc.), not for moza itself — pop it so google-auth
    # falls back to ~/.config/gcloud/application_default_credentials.json.
    os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)


_MARKDOWN_LINK = re.compile(r"^\[([^\]]+)\]\([^)]+\)$")


def _clean_email(s: str) -> str:
    s = s.strip()
    m = _MARKDOWN_LINK.match(s)
    return m.group(1) if m else s


def _read_secret(label: str, *, secret_cmd: str | None, from_stdin: bool) -> str:
    """Resolve a secret without it reaching argv, shell history, or ps.

    --secret-cmd: run the command, use its stdout (e.g. `op read op://...`).
                  Only the reference lands in history, never the secret.
    --token-stdin: read from a pipe.
    else: hidden interactive prompt (getpass — never echoed, never in argv).
    """
    if secret_cmd:
        try:
            out = subprocess.run(
                secret_cmd, shell=True, capture_output=True, text=True, check=True
            ).stdout
        except subprocess.CalledProcessError as exc:
            raise click.ClickException(
                f"--secret-cmd failed (exit {exc.returncode}): {(exc.stderr or '').strip()}"
            )
        secret = out.strip()
        if not secret:
            raise click.ClickException("--secret-cmd produced empty output")
        return secret
    if from_stdin:
        secret = sys.stdin.read().strip()
        if not secret:
            raise click.ClickException("--token-stdin set but stdin was empty")
        return secret
    return click.prompt(label, hide_input=True)


def _read_ssh_key(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        raise click.ClickException(
            f"SSH key not found at {path}.\n"
            f"Generate one with: ssh-keygen -t ed25519 -f {path}\n"
            f"Or pass an existing path with --ssh-key/--ssh-key-path."
        )


from contextlib import contextmanager


@contextmanager
def _readline_path_completion():
    """Enable tab completion for filesystem paths during a prompt."""
    try:
        import glob
        import readline
    except ImportError:
        yield
        return

    def completer(text: str, state: int):
        expanded = os.path.expanduser(text)
        matches = glob.glob(expanded + "*")
        matches = [m + "/" if os.path.isdir(m) else m for m in matches]
        if text.startswith("~"):
            home = os.path.expanduser("~")
            matches = [("~" + m[len(home):]) if m.startswith(home) else m for m in matches]
        return matches[state] if state < len(matches) else None

    prev_completer = readline.get_completer()
    prev_delims = readline.get_completer_delims()
    readline.set_completer(completer)
    readline.set_completer_delims(" \t\n")
    bind = "bind ^I rl_complete" if "libedit" in (readline.__doc__ or "") else "tab: complete"
    readline.parse_and_bind(bind)
    try:
        yield
    finally:
        readline.set_completer(prev_completer)
        readline.set_completer_delims(prev_delims)


def _validate_gcp_project_id(project: str) -> None:
    if " " in project or not project.islower():
        raise click.ClickException(
            f"{project!r} looks like a project NAME, not a PROJECT_ID.\n"
            "  Run `gcloud projects list` to find the PROJECT_ID column "
            "(lowercase, hyphens, e.g. 'my-first-project-12345')."
        )


def _verify_backend(backend, backend_type: str, bootstrap: dict) -> None:
    try:
        backend.health_check()
    except Exception as exc:
        msg = [f"backend health check failed: {exc}"]
        if backend_type == "gcp_secret_manager":
            account = bootstrap.get("gcp_account", "<bootstrap-email>")
            msg.append("")
            msg.append("Likely causes:")
            msg.append("  - Bootstrap ADC missing or for a different account.")
            msg.append("  - Bootstrap account lacks Secret Manager access on this project.")
            msg.append("")
            msg.append("Try:")
            msg.append(f"  gcloud auth application-default login --account={account}")
            msg.append(
                "  gcloud projects add-iam-policy-binding <project> \\\n"
                f"      --member=user:{account} --role=roles/secretmanager.admin"
            )
            msg.append("Then: moza doctor")
        elif backend_type == "oci_vault":
            msg.append("")
            msg.append("Check ~/.oci/config and that the API key PEM exists.")
            msg.append("Then: moza doctor")
        raise click.ClickException("\n".join(msg))


@main.command("init")
@click.option("--backend", type=click.Choice(["gcp_secret_manager", "oci_vault", "macos_keychain", "keyring"]),
              help="Skip the backend picker.")
@click.option("--project", help="(gcp) project ID")
@click.option("--bootstrap-email", help="(gcp) bootstrap account email")
@click.option("--vault-ocid", help="(oci) vault OCID")
@click.option("--compartment-ocid", help="(oci) compartment OCID")
@click.option("--region", default=None, help="(oci) region (default: ap-chuncheon-1)")
@click.option("--service-prefix", default=None, help="(keychain) service prefix (default: 'moza-')")
@click.option("--yes", "-y", is_flag=True, help="Overwrite existing config and auto-import an existing backend manifest without prompting.")
@click.option("--no-import", "no_import", is_flag=True,
              help="Skip importing an existing config manifest from the backend.")
def init_cmd(
    backend: str | None,
    project: str | None,
    bootstrap_email: str | None,
    vault_ocid: str | None,
    compartment_ocid: str | None,
    region: str | None,
    service_prefix: str | None,
    yes: bool,
    no_import: bool,
) -> None:
    """Bootstrap wizard. Supply flags for non-interactive setup; missing ones are prompted."""
    if config_path().exists():
        if yes:
            pass
        else:
            click.confirm(f"{config_path()} exists. Overwrite?", abort=True)

    if backend is None:
        click.echo("Pick a secrets backend:")
        click.echo("  1) gcp_secret_manager")
        click.echo("  2) oci_vault")
        click.echo("  3) macos_keychain")
        click.echo("  4) keyring (Linux Secret Service / Windows Credential Locker)")
        choice = click.prompt("Choice", type=click.Choice(["1", "2", "3", "4"]))
        backend = {"1": "gcp_secret_manager", "2": "oci_vault", "3": "macos_keychain", "4": "keyring"}[choice]

    if backend == "gcp_secret_manager":
        if not project:
            project = click.prompt("GCP project ID").strip()
        project = project.strip()
        _validate_gcp_project_id(project)
        if not bootstrap_email:
            bootstrap_email = click.prompt("Bootstrap GCP account email")
        bootstrap_email = _clean_email(bootstrap_email)
        backend_cfg = BackendConfig(type="gcp_secret_manager", options={"project": project})
        bootstrap = {"gcp_account": bootstrap_email}
    elif backend == "oci_vault":
        if not vault_ocid:
            vault_ocid = click.prompt("Vault OCID").strip()
        if not compartment_ocid:
            compartment_ocid = click.prompt("Compartment OCID").strip()
        if region is None:
            region = click.prompt("Region", default="ap-chuncheon-1")
        backend_cfg = BackendConfig(
            type="oci_vault",
            options={"vault_ocid": vault_ocid.strip(), "compartment_ocid": compartment_ocid.strip(), "region": region},
        )
        bootstrap = {}
    elif backend == "keyring":
        if service_prefix is None:
            service_prefix = click.prompt("Service prefix", default="moza-")
        backend_cfg = BackendConfig(type="keyring", options={"service_prefix": service_prefix})
        bootstrap = {}
    else:  # macos_keychain
        if service_prefix is None:
            service_prefix = click.prompt("Service prefix", default="moza-")
        backend_cfg = BackendConfig(type="macos_keychain", options={"service_prefix": service_prefix})
        bootstrap = {}

    cfg = Config(
        schema_version=1,
        secrets_backend=backend_cfg,
        bootstrap=bootstrap,
        secret_naming=SecretNaming(
            default="moza-{profile}-{service}-{kind}",
            slack_token="moza-{profile}-slack-{workspace}-token",
        ),
        profiles={},
    )
    save_config(cfg)
    click.echo(f"Wrote {config_path()}.")

    backend = load_backend(cfg.secrets_backend)
    _verify_backend(backend, backend_cfg.type, bootstrap)
    click.echo(f"Backend ({backend_cfg.type}): OK")

    if backend_cfg.type == "gcp_secret_manager":
        _set_adc_quota_project(backend_cfg.options["project"])

    if not no_import and is_cloud_backend(backend_cfg):
        try:
            remote = pull_manifest(backend)
        except Exception as exc:
            remote = None
            click.echo(f"(manifest check skipped: {exc})", err=True)
        if remote and remote.profiles:
            names = ", ".join(remote.profiles)
            do_import = yes or click.confirm(
                f"Found an existing moza config in this backend "
                f"({len(remote.profiles)} profiles: {names}). Import it?",
                default=True,
            )
            if do_import:
                save_config(remote)
                first = next(iter(remote.profiles))
                click.echo(
                    f'Imported {len(remote.profiles)} profiles. '
                    f'Try: eval "$(moza use {first})"'
                )
                return

    click.echo("Next: `moza login <profile> --service google|github|slack`")



def _print_oauth_client_hint(cfg: Config) -> None:
    """Show how to create an OAuth Desktop client when none is supplied."""
    if cfg.secrets_backend.type == "gcp_secret_manager":
        project = cfg.secrets_backend.options.get("project")
        url = f"https://console.cloud.google.com/apis/credentials?project={project}"
    else:
        url = "https://console.cloud.google.com/apis/credentials"
    click.echo("Need an OAuth Desktop client. If you don't have one yet:")
    click.echo(f"  1) Open: {url}")
    click.echo("  2) Create Credentials → OAuth client ID → Application type: Desktop app")
    click.echo("  3) Copy the Client ID + Client secret, then paste below.")
    click.echo("(One Desktop client can be reused across all moza profiles.)")
    click.echo("")


def _check_adc_quota_project(expected: str | None) -> None:
    """Read ADC file and warn if quota_project_id is missing or mismatched."""
    adc_path = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
    if not adc_path.exists():
        click.echo("ADC: not found", err=True)
        return
    try:
        adc = json.loads(adc_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        click.echo(f"ADC: unreadable ({e})", err=True)
        return
    actual = adc.get("quota_project_id")
    if not actual:
        click.echo(
            f"ADC quota project: not set (expected {expected!r})\n"
            f"  Fix: gcloud auth application-default set-quota-project {expected}",
            err=True,
        )
    elif expected and actual != expected:
        click.echo(
            f"ADC quota project: {actual!r} (expected {expected!r})\n"
            f"  Fix: gcloud auth application-default set-quota-project {expected}",
            err=True,
        )
    else:
        click.echo(f"ADC quota project: {actual}")


def _set_adc_quota_project(project: str) -> None:
    """Pin the ADC's quota_project_id so end-user creds aren't quota-orphaned."""
    try:
        subprocess.run(
            ["gcloud", "auth", "application-default", "set-quota-project", project],
            check=True,
            capture_output=True,
        )
        click.echo(f"Set ADC quota project to {project}.")
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        click.echo(
            f"warning: could not set ADC quota project ({exc}). "
            f"Run manually: gcloud auth application-default set-quota-project {project}",
            err=True,
        )


@main.command("list")
def list_cmd() -> None:
    cfg = _require_config()
    if not cfg.profiles:
        click.echo("(no profiles configured — run `moza login <name> --service ...`)")
        return
    for name, prof in cfg.profiles.items():
        services = []
        if prof.google:
            services.append(f"google:{prof.google.email}")
        if prof.github:
            services.append(f"github:{prof.github.username}")
        if prof.slack:
            services.append(f"slack:[{', '.join(w.workspace for w in prof.slack)}]")
        if prof.aws:
            parts = []
            if prof.aws.profile:
                parts.append(f"profile={prof.aws.profile}")
            if prof.aws.region:
                parts.append(f"region={prof.aws.region}")
            services.append(f"aws({','.join(parts) if parts else 'keys'})")
        if prof.oci:
            services.append(f"oci:{prof.oci.profile or 'DEFAULT'}")
        if prof.atlassian:
            services.append(f"atlassian:{prof.atlassian.email}")
        if prof.notion:
            services.append("notion")
        click.echo(f"{name}\t{' '.join(services) or '(empty)'}")


@main.command("status")
def status_cmd() -> None:
    active = os.environ.get("MOZA_PROFILE")
    if not active:
        click.echo("no profile active in this shell")
        return
    click.echo(f"active: {active}")
    for var in (
        "CLOUDSDK_ACTIVE_CONFIG_NAME",
        "CLOUDSDK_CORE_PROJECT",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GH_TOKEN",
        "MOZA_SLACK_TOKENS",
        "AWS_PROFILE",
        "AWS_DEFAULT_REGION",
        "AWS_ACCESS_KEY_ID",
        "OCI_CLI_PROFILE",
        "OCI_CLI_CONFIG_FILE",
        "ATLASSIAN_EMAIL",
        "ATLASSIAN_BASE_URL",
        "ATLASSIAN_API_TOKEN",
        "NOTION_TOKEN",
    ):
        if v := os.environ.get(var):
            shown = v if var not in ("GH_TOKEN", "AWS_ACCESS_KEY_ID", "ATLASSIAN_API_TOKEN", "NOTION_TOKEN") else "<set>"
            click.echo(f"  {var}={shown}")


@main.command("whoami")
@click.argument("profile", required=False)
@click.option(
    "--live", is_flag=True,
    help="Ask each provider who the profile actually authenticates as, and "
    "compare to the config. Exits non-zero on any mismatch or dead credential.",
)
def whoami_cmd(profile: str | None, live: bool) -> None:
    cfg = _require_config()
    name = profile or os.environ.get("MOZA_PROFILE")
    if not name:
        raise click.ClickException("no profile (set $MOZA_PROFILE or pass an argument)")
    prof = cfg.profiles.get(name)
    if not prof:
        raise click.ClickException(f"profile {name!r} not found")

    if live:
        _whoami_live(cfg, prof)
        return

    click.echo(json.dumps({
        "name": prof.name,
        "google": prof.google.email if prof.google else None,
        "github": prof.github.username if prof.github else None,
        "slack": [w.workspace for w in prof.slack],
        "aws": {"profile": prof.aws.profile, "region": prof.aws.region} if prof.aws else None,
        "oci": {"profile": prof.oci.profile} if prof.oci else None,
        "atlassian": {"email": prof.atlassian.email, "base_url": prof.atlassian.base_url} if prof.atlassian else None,
        "notion": True if prof.notion else None,
    }, indent=2))


def _whoami_live(cfg: Config, prof: Profile) -> None:
    """Probe each configured provider for its live identity and report it beside
    the configured value. A mismatch or a dead credential is a real problem and
    exits non-zero, so the command can gate a destructive action chained after
    it; a provider that could not be reached is surfaced but does not fail."""
    backend = load_backend(cfg.secrets_backend)
    bundle = build_env(prof, backend)
    env = {**os.environ, **bundle.env}

    results = []
    if prof.github:
        results.append(probe_github(prof.github.username, env))
    if prof.aws:
        results.append(probe_aws(prof.aws.profile, env))
    if prof.google and prof.google.refresh_token_ref and prof.google.oauth_client_secret_ref:
        results.append(probe_google(
            prof.google.email,
            prof.google.oauth_client_id,
            backend.get(prof.google.oauth_client_secret_ref).decode("utf-8"),
            backend.get(prof.google.refresh_token_ref).decode("utf-8"),
        ))

    if not results:
        raise click.ClickException(
            f"profile {prof.name!r} has no provider that supports live "
            "verification (github, aws, or google)"
        )

    click.echo(f"profile {prof.name!r} — live identity check\n")
    width = max(len(r.service) for r in results)
    for r in results:
        configured = r.configured if r.configured is not None else "(nothing to compare)"
        live_str = r.live if r.live is not None else "—"
        line = (f"  {r.service:<{width}}  {r.status.value.upper():<12} "
                f"configured={configured}  live={live_str}")
        if r.detail and r.status in (Status.UNAUTHORIZED, Status.UNREACHABLE, Status.UNAVAILABLE):
            line += f"\n  {'':<{width}}  {r.detail}"
        click.echo(line)

    problems = [r for r in results if r.status in (Status.MISMATCH, Status.UNAUTHORIZED)]
    if problems:
        services = ", ".join(r.service for r in problems)
        raise click.ClickException(
            f"live identity check failed for: {services}. "
            "The active credentials do not match this profile, or are dead."
        )


def _require_config() -> Config:
    cfg = load_config()
    if cfg is None:
        raise click.ClickException("no config — run `moza init` first")
    return cfg


def _save_and_sync(cfg: Config, backend) -> None:
    save_config(cfg)
    if is_cloud_backend(cfg.secrets_backend):
        try:
            push_manifest(cfg, backend)
        except Exception as exc:
            click.echo(
                f"warning: could not sync config manifest ({exc}). "
                f"Run `moza push` later.",
                err=True,
            )


def _reject_reserved_secret_name(profile_name: str, secret_naming: SecretNaming) -> None:
    """Reject a profile whose rendered secret names would collide with the
    reserved config-manifest secret. The default template can't collide, but a
    custom template might."""
    candidates = [
        profile_name,
        render_name(secret_naming.default, profile=profile_name,
                    service="probe", kind="probe"),
        render_name(secret_naming.slack_token, profile=profile_name,
                    workspace="probe"),
    ]
    if MANIFEST_SECRET_NAME in candidates:
        raise click.ClickException(
            f"profile {profile_name!r} would collide with the reserved "
            f"config-manifest secret {MANIFEST_SECRET_NAME!r}; "
            f"rename the profile or adjust secret_naming"
        )


@main.command("login")
@click.argument("profile_name")
@click.option("--service", type=click.Choice(["google", "github", "slack", "aws", "oci", "atlassian", "notion"]), required=True)
@click.option("--workspace", help="Slack workspace label (required for --service slack)")
@click.option("--email", help="(google) account email")
@click.option("--username", help="(github) username")
@click.option("--host", default="github.com", help="(github) host (for GHES)")
@click.option("--ssh-key-path", "ssh_key_path", help="(github) register SSH key by path (per-device)")
@click.option("--ssh-key", "ssh_key", help="(github) read SSH key file and store contents in the secrets backend")
@click.option("--token-stdin", "token_stdin", is_flag=True,
              help="(github/slack/aws/atlassian/notion) read the secret from stdin instead of prompting")
@click.option("--secret-cmd", "secret_cmd",
              help="Run this command and use its stdout as the secret "
                   "(e.g. 'op read op://Private/item/field'). Keeps the secret out of argv/history.")
@click.option("--refresh-token-stdin", "refresh_token_stdin", is_flag=True,
              help="(google) read an existing refresh token from stdin instead of running the browser flow")
@click.option("--client-id", help="(google) OAuth client ID")
@click.option("--access-key-id", "access_key_id", help="(aws) AWS access key ID")
@click.option("--aws-profile", "aws_profile", help="(aws) existing ~/.aws profile name")
@click.option("--oci-profile", "oci_profile", help="(oci) existing ~/.oci/config profile name")
@click.option("--config-file", "config_file", help="(oci) path to OCI config file (default: ~/.oci/config)")
@click.option("--region", "region", help="(aws) default region")
@click.option("--atlassian-email", "atlassian_email", help="(atlassian) account email")
@click.option("--base-url", "base_url", help="(atlassian) base URL (e.g. https://yourco.atlassian.net)")
def login_cmd(
    profile_name: str,
    service: str,
    workspace: str | None,
    email: str | None,
    username: str | None,
    host: str,
    ssh_key_path: str | None,
    ssh_key: str | None,
    token_stdin: bool,
    secret_cmd: str | None,
    refresh_token_stdin: bool,
    client_id: str | None,
    access_key_id: str | None,
    aws_profile: str | None,
    oci_profile: str | None,
    config_file: str | None,
    region: str | None,
    atlassian_email: str | None,
    base_url: str | None,
) -> None:
    cfg = _require_config()
    if profile_name not in cfg.profiles:
        click.confirm(f"Profile {profile_name!r} not found. Create it?", default=False, abort=True)
    backend = load_backend(cfg.secrets_backend)
    _reject_reserved_secret_name(profile_name, cfg.secret_naming)

    if service == "github":
        prof = cfg.profiles.get(profile_name) or Profile(name=profile_name)
        gh = prof.github or GitHubService(
            username=username or "",
            host=host,
        )
        if username:
            gh.username = username
        gh.host = host

        did_something = False

        if ssh_key_path:
            gh.ssh_key_path = str(Path(ssh_key_path).expanduser())
            click.echo(f"registered ssh key path for {profile_name}: {gh.ssh_key_path}")
            did_something = True

        if ssh_key:
            content = _read_ssh_key(Path(ssh_key).expanduser())
            ref_name = render_name(cfg.secret_naming.default, profile=profile_name, service="github", kind="ssh_key")
            gh.ssh_key_ref = backend.put(ref_name, content)
            click.echo(f"stored ssh key for {profile_name} at {gh.ssh_key_ref}")
            did_something = True

        if not (ssh_key_path or ssh_key):
            if not gh.username:
                gh.username = click.prompt("GitHub username")
            token = _read_secret("Paste a GitHub token", secret_cmd=secret_cmd, from_stdin=token_stdin)
            ref_name = render_name(cfg.secret_naming.default, profile=profile_name, service="github", kind="token")
            gh.token_ref = backend.put(ref_name, token.encode("utf-8"))
            click.echo(f"stored github token for {profile_name} at {gh.token_ref}")
            did_something = True

            if not token_stdin and click.confirm("Also register an SSH key for git operations?", default=False):
                default_path = str(Path.home() / ".ssh" / "id_ed25519")
                with _readline_path_completion():
                    path = click.prompt("SSH private key path", default=default_path)
                expanded = Path(path).expanduser()
                if not expanded.exists():
                    raise click.ClickException(
                        f"SSH key not found at {expanded}.\n"
                        f"Generate one with: ssh-keygen -t ed25519 -f {expanded}"
                    )
                storage = click.prompt(
                    "Store key in the secrets backend (sm) or remember the path only (path)?",
                    type=click.Choice(["sm", "path"]),
                    default="sm",
                )
                if storage == "path":
                    gh.ssh_key_path = str(expanded)
                    click.echo(f"registered ssh key path: {gh.ssh_key_path}")
                else:
                    content = expanded.read_bytes()
                    ssh_ref_name = render_name(cfg.secret_naming.default, profile=profile_name, service="github", kind="ssh_key")
                    gh.ssh_key_ref = backend.put(ssh_ref_name, content)
                    click.echo(f"stored ssh key contents at {gh.ssh_key_ref}")

        if did_something:
            prof.github = gh
            cfg.profiles[profile_name] = prof
            _save_and_sync(cfg, backend)
        return

    if service == "slack":
        if not workspace:
            raise click.ClickException("--workspace is required for --service slack")
        token = _read_secret("Paste a Slack user token (xoxp-...)", secret_cmd=secret_cmd, from_stdin=token_stdin)
        ref_name = render_name(cfg.secret_naming.slack_token, profile=profile_name, workspace=workspace)
        ref = backend.put(ref_name, token.encode("utf-8"))
        prof = cfg.profiles.get(profile_name) or Profile(name=profile_name)
        prof.slack = [w for w in prof.slack if w.workspace != workspace]
        prof.slack.append(SlackWorkspace(workspace=workspace, team_id=None, user_token_ref=ref))
        cfg.profiles[profile_name] = prof
        _save_and_sync(cfg, backend)
        click.echo(f"stored slack token for {profile_name}/{workspace} at {ref}")
        return

    if service == "google":
        email = email or click.prompt("Google account email")
        if not client_id:
            _print_oauth_client_hint(cfg)
            client_id = click.prompt("OAuth client ID")
        client_secret = _read_secret("OAuth client secret", secret_cmd=secret_cmd, from_stdin=False)

        if refresh_token_stdin:
            refresh = sys.stdin.read().strip()
            if not refresh:
                raise click.ClickException("--refresh-token-stdin set but stdin was empty")
        else:
            refresh = google_installed_app_flow(
                client_id=client_id,
                client_secret=client_secret,
                scopes=GOOGLE_DEFAULT_SCOPES,
            )
        oauth_secret_ref = backend.put(
            render_name(cfg.secret_naming.default, profile=profile_name, service="google", kind="oauth_client_secret"),
            client_secret.encode("utf-8"),
        )
        refresh_ref = backend.put(
            render_name(cfg.secret_naming.default, profile=profile_name, service="google", kind="refresh"),
            refresh.encode("utf-8"),
        )

        prof = cfg.profiles.get(profile_name) or Profile(name=profile_name)
        prof.google = GoogleService(
            email=email,
            oauth_client_id=client_id,
            oauth_client_secret_ref=oauth_secret_ref,
            refresh_token_ref=refresh_ref,
            adc_ref=None,
            gcloud_config_name=profile_name,
            default_project=None,
            gcloud_login_required=False,
        )
        cfg.profiles[profile_name] = prof
        _save_and_sync(cfg, backend)
        click.echo(f"stored google identity for {profile_name}")
        return

    if service == "aws":
        prof = cfg.profiles.get(profile_name) or Profile(name=profile_name)
        aws = prof.aws or AWSService()
        if region:
            aws.region = region
        if aws_profile:
            aws.profile = aws_profile
        if access_key_id:
            key_id = access_key_id
            secret = _read_secret("AWS secret access key", secret_cmd=secret_cmd, from_stdin=token_stdin)
            ref_id = backend.put(
                render_name(cfg.secret_naming.default, profile=profile_name, service="aws", kind="access_key_id"),
                key_id.encode("utf-8"),
            )
            ref_secret = backend.put(
                render_name(cfg.secret_naming.default, profile=profile_name, service="aws", kind="secret_access_key"),
                secret.encode("utf-8"),
            )
            aws.access_key_id_ref = ref_id
            aws.secret_access_key_ref = ref_secret
            click.echo(f"stored AWS credentials for {profile_name}")
        elif not aws_profile and not region:
            choice = click.prompt(
                "Store AWS credentials (keys) or reference an existing ~/.aws profile?",
                type=click.Choice(["keys", "profile"]),
                default="keys",
            )
            if choice == "profile":
                aws.profile = click.prompt("~/.aws profile name", default="default")
                aws.region = click.prompt("Default region (optional, blank to skip)", default="", show_default=False) or None
            else:
                key_id = click.prompt("AWS access key ID")
                secret = _read_secret("AWS secret access key", secret_cmd=secret_cmd, from_stdin=False)
                aws.region = click.prompt("Default region (optional, blank to skip)", default="", show_default=False) or None
                ref_id = backend.put(
                    render_name(cfg.secret_naming.default, profile=profile_name, service="aws", kind="access_key_id"),
                    key_id.encode("utf-8"),
                )
                ref_secret = backend.put(
                    render_name(cfg.secret_naming.default, profile=profile_name, service="aws", kind="secret_access_key"),
                    secret.encode("utf-8"),
                )
                aws.access_key_id_ref = ref_id
                aws.secret_access_key_ref = ref_secret
                click.echo(f"stored AWS credentials for {profile_name}")
        prof.aws = aws
        cfg.profiles[profile_name] = prof
        _save_and_sync(cfg, backend)
        return

    if service == "oci":
        prof = cfg.profiles.get(profile_name) or Profile(name=profile_name)
        oci = prof.oci or OCIService()
        if oci_profile:
            oci.profile = oci_profile
        if config_file:
            oci.config_file = config_file
        if not oci_profile and not config_file:
            oci.profile = click.prompt("~/.oci/config profile name", default="DEFAULT")
            cf = click.prompt("Custom OCI config file path (blank for default ~/.oci/config)", default="", show_default=False)
            if cf:
                oci.config_file = str(Path(cf).expanduser())
        prof.oci = oci
        cfg.profiles[profile_name] = prof
        _save_and_sync(cfg, backend)
        click.echo(f"stored OCI identity for {profile_name} (profile={oci.profile!r})")
        return

    if service == "atlassian":
        prof = cfg.profiles.get(profile_name) or Profile(name=profile_name)
        email_val = atlassian_email or (prof.atlassian.email if prof.atlassian else None) or click.prompt("Atlassian account email")
        url = base_url or (prof.atlassian.base_url if prof.atlassian else None) or click.prompt("Atlassian base URL (e.g. https://yourco.atlassian.net)")
        token = _read_secret("Atlassian API token", secret_cmd=secret_cmd, from_stdin=token_stdin)
        ref = backend.put(
            render_name(cfg.secret_naming.default, profile=profile_name, service="atlassian", kind="api_token"),
            token.encode("utf-8"),
        )
        prof.atlassian = AtlassianService(email=email_val, base_url=url.rstrip("/"), api_token_ref=ref)
        cfg.profiles[profile_name] = prof
        _save_and_sync(cfg, backend)
        click.echo(f"stored atlassian identity for {profile_name} at {ref}")
        return

    if service == "notion":
        prof = cfg.profiles.get(profile_name) or Profile(name=profile_name)
        token = _read_secret("Notion integration token", secret_cmd=secret_cmd, from_stdin=token_stdin)
        ref = backend.put(
            render_name(cfg.secret_naming.default, profile=profile_name, service="notion", kind="api_token"),
            token.encode("utf-8"),
        )
        prof.notion = NotionService(api_token_ref=ref)
        cfg.profiles[profile_name] = prof
        _save_and_sync(cfg, backend)
        click.echo(f"stored notion identity for {profile_name} at {ref}")
        return


def _stdout_is_tty() -> bool:
    """Indirection so tests can flip the heuristic without monkey-patching
    sys.stdout (which Click's CliRunner replaces during invoke)."""
    return sys.stdout.isatty()


@main.command("use")
@click.argument("profile_name")
@click.option("--print", "force_print", is_flag=True,
              help="Force emitting the loader to stdout even if stdout is a TTY. "
                   "Use only when you understand the snippet sources an env file "
                   "and won't paste the path anywhere it shouldn't go.")
def use_cmd(profile_name: str, force_print: bool) -> None:
    if _stdout_is_tty() and not force_print:
        raise click.ClickException(
            "stdout is a TTY — refusing to emit the env loader.\n"
            "`moza use` is meant to be eval'd, not run interactively.\n\n"
            "Use the wrapper (recommended):\n"
            f"  moza-use {profile_name}\n\n"
            "Or eval directly:\n"
            f'  eval "$(moza use {profile_name})"\n\n'
            "If you really need raw output, pass --print."
        )
    cfg = _require_config()
    prof = cfg.profiles.get(profile_name)
    if not prof:
        raise click.ClickException(f"profile {profile_name!r} not found")
    backend = load_backend(cfg.secrets_backend)
    bundle = build_env(prof, backend)
    sys.stdout.write(emit_use(bundle))


def _profile_fingerprint(prof) -> str:
    """Stable JSON of a Profile for change detection. sort_keys neutralises
    dict ordering; assumes all profile fields are JSON-serializable (they are:
    str/None/bool and lists of dataclasses)."""
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
    if removed:
        click.echo(
            f"WARNING: these local-only profiles will be DROPPED: {', '.join(removed)}",
            err=True,
        )
    if not yes:
        click.confirm("Replace local config with the manifest?", default=True, abort=True)
    save_config(remote)
    click.echo(f"synced {len(remote.profiles)} profiles from manifest")


@main.command("push")
def push_cmd() -> None:
    """Force-push the current local config to the backend manifest."""
    cfg = _require_config()
    if not is_cloud_backend(cfg.secrets_backend):
        # Intentionally exit 0 (not an error like sync): pushing a manifest to a
        # local-only backend is simply meaningless, not a user mistake.
        click.echo("push is a no-op for local backends (macos_keychain)")
        return
    backend = load_backend(cfg.secrets_backend)
    push_manifest(cfg, backend)
    click.echo("pushed config manifest to backend")


@main.group("env", cls=MozaGroup)
def env_group() -> None:
    """Manage ambient per-project env (non-interactive zsh only)."""


def _warn_unexpandable_scopes(profiles: dict[str, Profile]) -> None:
    """Warn about `project_env` scopes whose variables are unset where they run.

    The generated script is sourced from `~/.zshenv`, which zsh reads BEFORE
    `~/.zshrc` and `~/.zprofile` — so a variable the user exports from their own
    dotfiles is unset by construction at match time. zsh expands it to nothing,
    and `case "$PWD/" in $WORK_ROOT/*)` becomes `/*`, which matches every
    absolute path: every shell would get that scope's env, including the
    credential-selecting kind (`AWS_PROFILE`).

    Warn and continue rather than reject: a config that works today (because the
    variable happens to be exported early enough, or because the scope's other
    segments make the collapse harmless) must not start failing on upgrade.
    """
    for name in sorted(profiles):
        for scope in profiles[name].project_env:
            missing = unexpandable_scope_vars(scope.match)
            if not missing:
                continue
            refs = ", ".join(f"${v}" for v in missing)
            click.echo(
                f"warning: profile {name!r} scope {scope.match!r} refers to {refs}, "
                "which will be unset where it is evaluated: the generated script is "
                "sourced from ~/.zshenv, and zsh reads that BEFORE ~/.zshrc and "
                "~/.zprofile, so variables defined there do not exist yet. zsh "
                "expands the reference to nothing, which can widen the scope to "
                "directories you did not intend. Write a literal path instead, or "
                "'~', which expands correctly this early.",
                err=True,
            )


@env_group.command("sync")
def env_sync_cmd() -> None:
    """Generate ~/.config/moza/ambient.zsh from every profile's project_env and
    ensure ~/.zshenv sources it. Non-secret only. Idempotent. The generated
    script is `zsh -n`-validated before anything is written or wired."""
    cfg = _require_config()
    _warn_unexpandable_scopes(cfg.profiles)
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


@main.command("unset")
def unset_cmd() -> None:
    sys.stdout.write(emit_unset())


def _run_as_profile(cfg: Config, prof: Profile, argv: tuple[str, ...]) -> None:
    """Run argv with the profile's env, then exit with the child's status.

    Shared by `exec` and `run` so the cleanup below cannot drift between them.

    Whichever command spawns the child owns its whole lifetime, so it also owns
    the plaintext credential files build_env drops in $TMPDIR/moza (ADC blob with
    the client_secret + refresh_token, ssh key, slack token map). Unlike `use`,
    nothing downstream needs them to survive this process — and no shell EXIT trap
    fires for these paths, since MOZA_PROFILE is only ever set in the child's
    environment. Clean up unconditionally: normal exit, non-zero exit, child
    killed by a signal, Ctrl-C, or an exception.
    """
    backend = load_backend(cfg.secrets_backend)
    store = EphemeralStore()
    try:
        bundle = build_env(prof, backend, pid=store.pid)
        env = {**os.environ, **bundle.env}
        rc = subprocess.call(list(argv), env=env)
    finally:
        store.cleanup()
    sys.exit(rc)


@main.command("exec", context_settings={"ignore_unknown_options": True})
@click.argument("profile_name")
@click.argument("argv", nargs=-1, required=True)
def exec_cmd(profile_name: str, argv: tuple[str, ...]) -> None:
    cfg = _require_config()
    prof = cfg.profiles.get(profile_name)
    if not prof:
        raise click.ClickException(f"profile {profile_name!r} not found")
    _run_as_profile(cfg, prof, argv)


def _logical_cwd() -> str:
    """The working directory as the shell names it: `$PWD` when it is honest.

    `os.getcwd()` resolves symlinks; the shell's `$PWD` does not. Standing in a
    directory reached through a symlink — `/tmp` -> `/private/tmp`, a relocated
    home, a projects tree on an external volume — the two disagree, and a scope
    like '*/Projects/acme' that the generated `case "$PWD/" in ...` matches would
    not match the physical path. Preferring `$PWD` keeps identity resolution
    answering about the same directory ambient env answers about.

    `$PWD` is trusted only after `os.path.samefile` confirms it is the directory we
    are actually in: it is inherited across `cd`-less subprocesses and can be stale,
    unset, or a lie, and a stale value would resolve to some other project's
    credentials. Any doubt falls back to the physical path.
    """
    physical = os.getcwd()
    pwd = os.environ.get("PWD")
    if pwd and os.path.isabs(pwd) and pwd != physical:
        try:
            if os.path.samefile(pwd, physical):
                return pwd
        except OSError:
            pass
    return physical


def _resolve_cwd_profile(cfg: Config) -> str | None:
    """Profile claimed by the current directory, honouring an explicit override.

    An activated MOZA_PROFILE wins: someone ran `moza use` on purpose and a
    directory default must not quietly undo that. The disagreement is still
    reported, because acting against the directory's default without noticing is
    the confusion this resolution exists to remove.

    An ambiguous directory only blocks the commands that would otherwise have to
    guess. With an override in hand there is nothing to guess, so the clash is
    reported on stderr and the activated profile is used.

    A name returned from here is always a profile that exists. Directory scopes
    come from the config, so only the override can name something else — a
    renamed or deleted profile leaves a stale MOZA_PROFILE exported in shells
    that are still open. Rejecting it here, rather than in each caller, keeps
    `which` from printing a name its own consumers cannot use.
    """
    active = os.environ.get("MOZA_PROFILE")
    if active and active not in cfg.profiles:
        raise click.ClickException(
            f"profile {active!r} is active in this shell but not found in the "
            "config; it may have been renamed or removed. Clear it with "
            "`moza-unset` (bare `moza unset` only prints the commands — it "
            "cannot change the calling shell), or activate an existing profile."
        )
    try:
        from_dir = resolve_profile(cfg.profiles, _logical_cwd())
    except AmbiguousScope as exc:
        if not active:
            raise click.ClickException(str(exc)) from exc
        click.echo(
            f"warning: this directory is claimed by several profiles with equal "
            f"specificity, but {active!r} is active in this shell; using {active!r}",
            err=True,
        )
        return active

    if active:
        if from_dir and from_dir != active:
            click.echo(
                f"warning: this directory defaults to {from_dir!r}, but "
                f"{active!r} is active in this shell; using {active!r}",
                err=True,
            )
        return active
    return from_dir


@main.command("which")
def which_cmd() -> None:
    """Print the profile for the current directory, or exit non-zero."""
    name = _resolve_cwd_profile(_require_config())
    if not name:
        # Deliberately silent on stdout: callers substitute this into other
        # commands, so printing anything here would be taken for a profile name.
        raise click.ClickException(
            f"no profile claims {_logical_cwd()}. Add a default_for scope to a "
            "profile, or name one explicitly."
        )
    click.echo(name)


@main.command("run", context_settings={"ignore_unknown_options": True})
@click.argument("argv", nargs=-1, required=True)
def run_cmd(argv: tuple[str, ...]) -> None:
    """Run a command as the profile claimed by the current directory."""
    cfg = _require_config()
    name = _resolve_cwd_profile(cfg)
    if not name:
        raise click.ClickException(
            f"no profile claims {_logical_cwd()}. Add a default_for scope to a "
            "profile, or use `moza exec <profile> -- ...`."
        )
    # _resolve_cwd_profile only ever returns a profile that exists.
    _run_as_profile(cfg, cfg.profiles[name], argv)


@main.command("token")
@click.argument("service", type=click.Choice(["google", "atlassian", "notion"]))
@click.option(
    "--profile",
    "profile",
    default=None,
    help="Profile to mint for. Defaults to $MOZA_PROFILE. Prefer passing this "
    "explicitly from an agent, whose shell state does not survive between calls.",
)
def token_cmd(service: str, profile: str | None) -> None:
    cfg = _require_config()
    name = profile or os.environ.get("MOZA_PROFILE")
    if not name:
        raise click.ClickException(
            "no profile: pass --profile <name>, or set $MOZA_PROFILE via "
            'eval "$(moza use <profile>)" in this same shell'
        )
    prof = cfg.profiles.get(name)
    if not prof:
        raise click.ClickException(f"profile {name!r} not found")
    backend = load_backend(cfg.secrets_backend)
    if service == "google":
        if not prof.google:
            raise click.ClickException(f"profile {name!r} has no google identity")
        g = prof.google
        client_secret = backend.get(g.oauth_client_secret_ref).decode("utf-8")
        refresh = backend.get(g.refresh_token_ref).decode("utf-8")
        access = exchange_refresh_token(
            client_id=g.oauth_client_id,
            client_secret=client_secret,
            refresh_token=refresh,
        )
        click.echo(access)
    elif service == "atlassian":
        if not prof.atlassian:
            raise click.ClickException(f"profile {name!r} has no atlassian identity")
        token = backend.get(prof.atlassian.api_token_ref).decode("utf-8").strip()
        click.echo(token)
    elif service == "notion":
        if not prof.notion:
            raise click.ClickException(f"profile {name!r} has no notion identity")
        token = backend.get(prof.notion.api_token_ref).decode("utf-8").strip()
        click.echo(token)


@main.command("logout")
@click.argument("profile_name")
@click.option("--service", type=click.Choice(["google", "github", "slack", "aws", "oci", "atlassian", "notion"]), required=True)
@click.option("--workspace", help="Slack workspace label (required for --service slack)")
def logout_cmd(profile_name: str, service: str, workspace: str | None) -> None:
    cfg = _require_config()
    prof = cfg.profiles.get(profile_name)
    if not prof:
        raise click.ClickException(f"profile {profile_name!r} not found")
    backend = load_backend(cfg.secrets_backend)
    if service == "github" and prof.github:
        if prof.github.token_ref:
            backend.delete(prof.github.token_ref)
        if prof.github.ssh_key_ref:
            backend.delete(prof.github.ssh_key_ref)
        prof.github = None
    elif service == "google" and prof.google:
        if prof.google.refresh_token_ref:
            backend.delete(prof.google.refresh_token_ref)
        if prof.google.oauth_client_secret_ref:
            backend.delete(prof.google.oauth_client_secret_ref)
        if prof.google.adc_ref:
            backend.delete(prof.google.adc_ref)
        prof.google = None
    elif service == "slack":
        if not workspace:
            raise click.ClickException("--workspace required for --service slack")
        kept = []
        for w in prof.slack:
            if w.workspace == workspace:
                backend.delete(w.user_token_ref)
            else:
                kept.append(w)
        prof.slack = kept
    elif service == "aws" and prof.aws:
        if prof.aws.access_key_id_ref:
            backend.delete(prof.aws.access_key_id_ref)
        if prof.aws.secret_access_key_ref:
            backend.delete(prof.aws.secret_access_key_ref)
        prof.aws = None
    elif service == "oci":
        prof.oci = None
    elif service == "atlassian" and prof.atlassian:
        backend.delete(prof.atlassian.api_token_ref)
        prof.atlassian = None
    elif service == "notion" and prof.notion:
        backend.delete(prof.notion.api_token_ref)
        prof.notion = None
    _save_and_sync(cfg, backend)
    click.echo(f"removed {service} from {profile_name}")


@main.command("doctor")
@click.option("--gc", is_flag=True, help="Sweep stale ephemeral files for dead PIDs")
def doctor_cmd(gc: bool) -> None:
    cfg = _require_config()
    click.echo(f"config:    {config_path()}")
    click.echo(f"backend:   {cfg.secrets_backend.type}")
    for k, v in cfg.secrets_backend.options.items():
        click.echo(f"             {k}={v}")
    for k, v in (cfg.bootstrap or {}).items():
        click.echo(f"bootstrap: {k}={v}")
    names = ", ".join(cfg.profiles) or "(none)"
    click.echo(f"profiles:  {len(cfg.profiles)} [{names}]")

    backend = load_backend(cfg.secrets_backend)
    try:
        backend.health_check()
    except Exception as e:
        raise click.ClickException(f"backend health check failed: {e}")
    click.echo("backend health: OK")

    if cfg.secrets_backend.type == "gcp_secret_manager":
        _check_adc_quota_project(cfg.secrets_backend.options.get("project"))

    if gc:
        EphemeralStore.gc()
        click.echo("ephemeral GC: done")


@main.command("preflight")
@click.option("--backend", type=click.Choice(["gcp_secret_manager", "oci_vault", "macos_keychain"]),
              default="gcp_secret_manager", help="Backend to check prerequisites for.")
@click.option("--project", help="(gcp) project to verify access on")
@click.option("--account", help="(gcp) account email to verify")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON for agent orchestration.")
def preflight_cmd(backend: str, project: str | None, account: str | None, as_json: bool) -> None:
    """Check environment readiness before `moza init`. Useful for agent-driven setup."""
    findings: list[dict] = []

    def add(name: str, ok: bool, detail: str = "", fix: str = "") -> None:
        findings.append({"check": name, "ok": ok, "detail": detail, "fix": fix})

    if backend == "gcp_secret_manager":
        try:
            r = subprocess.run(["gcloud", "--version"], capture_output=True, text=True, check=True)
            first = (r.stdout.splitlines() or [""])[0]
            add("gcloud installed", True, first)
        except (FileNotFoundError, subprocess.CalledProcessError):
            add("gcloud installed", False, "", "Install Google Cloud SDK: https://cloud.google.com/sdk/docs/install")

        if project:
            cmd = ["gcloud", "projects", "describe", project]
            if account:
                cmd.append(f"--account={account}")
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode == 0:
                add(f"project {project!r} accessible", True)
            else:
                add(f"project {project!r} accessible", False, r.stderr.strip().splitlines()[-1] if r.stderr else "",
                    f"gcloud projects list --account={account or '<email>'}  # find the right project ID")

            r = subprocess.run(
                ["gcloud", "services", "list", "--enabled", f"--project={project}",
                 "--filter=config.name:secretmanager.googleapis.com", "--format=value(config.name)"]
                + ([f"--account={account}"] if account else []),
                capture_output=True, text=True,
            )
            enabled = "secretmanager.googleapis.com" in r.stdout
            if enabled:
                add("Secret Manager API enabled", True)
            else:
                add("Secret Manager API enabled", False, "",
                    f"gcloud services enable secretmanager.googleapis.com --project={project}"
                    + (f" --account={account}" if account else ""))

        adc_path = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
        if adc_path.exists():
            try:
                adc = json.loads(adc_path.read_text())
                qp = adc.get("quota_project_id")
                add("ADC present", True, f"quota_project_id={qp or '(unset)'}")
            except (OSError, json.JSONDecodeError) as e:
                add("ADC present", False, str(e),
                    f"gcloud auth application-default login --account={account or '<email>'}")
        else:
            add("ADC present", False, "no application_default_credentials.json",
                f"gcloud auth application-default login --account={account or '<email>'}")

    elif backend == "oci_vault":
        oci_cfg = Path.home() / ".oci" / "config"
        add("~/.oci/config", oci_cfg.exists(), "",
            "Create an API key in OCI Console and run `oci setup config`")

    elif backend == "macos_keychain":
        try:
            subprocess.run(["security", "list-keychains"], capture_output=True, check=True)
            add("security CLI", True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            add("security CLI", False, "", "macOS only — this backend isn't supported on this OS")

    if as_json:
        click.echo(json.dumps({"backend": backend, "checks": findings}, indent=2))
        if any(not f["ok"] for f in findings):
            sys.exit(1)
        return

    for f in findings:
        mark = "✓" if f["ok"] else "✗"
        line = f"  {mark} {f['check']}"
        if f["detail"]:
            line += f" — {f['detail']}"
        click.echo(line)
        if not f["ok"] and f["fix"]:
            click.echo(f"      fix: {f['fix']}")
    if any(not f["ok"] for f in findings):
        sys.exit(1)
