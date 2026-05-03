from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import click

from hat.backends import load_backend
from hat.ephemeral import EphemeralStore
from hat.config import (
    BackendConfig,
    Config,
    GitHubService,
    GoogleService,
    Profile,
    SecretNaming,
    SlackWorkspace,
    config_path,
    load_config,
    save_config,
)
from hat.env import build_env
from hat.oauth import exchange_refresh_token, google_installed_app_flow
from hat.secret_naming import render_name
from hat.shell import emit_unset, emit_use


GOOGLE_DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/cloud-platform",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]


@click.group()
@click.version_option(package_name="hat-cli")
def main() -> None:
    """hat — multi-identity credential router."""


_MARKDOWN_LINK = re.compile(r"^\[([^\]]+)\]\([^)]+\)$")


def _clean_email(s: str) -> str:
    s = s.strip()
    m = _MARKDOWN_LINK.match(s)
    return m.group(1) if m else s


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
            msg.append("Then: hat doctor")
        elif backend_type == "oci_vault":
            msg.append("")
            msg.append("Check ~/.oci/config and that the API key PEM exists.")
            msg.append("Then: hat doctor")
        raise click.ClickException("\n".join(msg))


@main.command("init")
def init_cmd() -> None:
    """Interactive bootstrap wizard."""
    if config_path().exists():
        click.confirm(f"{config_path()} exists. Overwrite?", abort=True)

    click.echo("Pick a secrets backend:")
    click.echo("  1) gcp_secret_manager")
    click.echo("  2) oci_vault")
    click.echo("  3) macos_keychain")
    choice = click.prompt("Choice", type=click.Choice(["1", "2", "3"]))

    if choice == "1":
        project = click.prompt("GCP project ID").strip()
        _validate_gcp_project_id(project)
        bootstrap_account = _clean_email(click.prompt("Bootstrap GCP account email"))
        backend_cfg = BackendConfig(type="gcp_secret_manager", options={"project": project})
        bootstrap = {"gcp_account": bootstrap_account}
    elif choice == "2":
        vault_ocid = click.prompt("Vault OCID").strip()
        compartment_ocid = click.prompt("Compartment OCID").strip()
        region = click.prompt("Region", default="ap-chuncheon-1")
        backend_cfg = BackendConfig(
            type="oci_vault",
            options={"vault_ocid": vault_ocid, "compartment_ocid": compartment_ocid, "region": region},
        )
        bootstrap = {}
    else:
        prefix = click.prompt("Service prefix", default="hat-")
        backend_cfg = BackendConfig(type="macos_keychain", options={"service_prefix": prefix})
        bootstrap = {}

    cfg = Config(
        schema_version=1,
        secrets_backend=backend_cfg,
        bootstrap=bootstrap,
        secret_naming=SecretNaming(
            default="hat-{profile}-{service}-{kind}",
            slack_token="hat-{profile}-slack-{workspace}-token",
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

    click.echo("Next: `hat login <profile> --service google|github|slack`")


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
    click.echo("(One Desktop client can be reused across all hat profiles.)")
    click.echo("")


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
        click.echo("(no profiles configured — run `hat login <name> --service ...`)")
        return
    for name, prof in cfg.profiles.items():
        services = []
        if prof.google:
            services.append(f"google:{prof.google.email}")
        if prof.github:
            services.append(f"github:{prof.github.username}")
        if prof.slack:
            services.append(f"slack:[{', '.join(w.workspace for w in prof.slack)}]")
        click.echo(f"{name}\t{' '.join(services) or '(empty)'}")


@main.command("status")
def status_cmd() -> None:
    active = os.environ.get("HAT_PROFILE")
    if not active:
        click.echo("no profile active in this shell")
        return
    click.echo(f"active: {active}")
    for var in (
        "CLOUDSDK_ACTIVE_CONFIG_NAME",
        "CLOUDSDK_CORE_PROJECT",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GH_TOKEN",
        "HAT_SLACK_TOKENS",
    ):
        if v := os.environ.get(var):
            shown = v if var != "GH_TOKEN" else "<set>"
            click.echo(f"  {var}={shown}")


@main.command("whoami")
@click.argument("profile", required=False)
def whoami_cmd(profile: str | None) -> None:
    cfg = _require_config()
    name = profile or os.environ.get("HAT_PROFILE")
    if not name:
        raise click.ClickException("no profile (set $HAT_PROFILE or pass an argument)")
    prof = cfg.profiles.get(name)
    if not prof:
        raise click.ClickException(f"profile {name!r} not found")
    click.echo(json.dumps({
        "name": prof.name,
        "google": prof.google.email if prof.google else None,
        "github": prof.github.username if prof.github else None,
        "slack": [w.workspace for w in prof.slack],
    }, indent=2))


def _require_config() -> Config:
    cfg = load_config()
    if cfg is None:
        raise click.ClickException("no config — run `hat init` first")
    return cfg


@main.command("login")
@click.argument("profile_name")
@click.option("--service", type=click.Choice(["google", "github", "slack"]), required=True)
@click.option("--workspace", help="Slack workspace label (required for --service slack)")
@click.option("--email", help="(google) account email")
@click.option("--username", help="(github) username")
@click.option("--host", default="github.com", help="(github) host (for GHES)")
@click.option("--client-id", help="(google) OAuth client ID")
def login_cmd(
    profile_name: str,
    service: str,
    workspace: str | None,
    email: str | None,
    username: str | None,
    host: str,
    client_id: str | None,
) -> None:
    cfg = _require_config()
    backend = load_backend(cfg.secrets_backend)

    if service == "github":
        username = username or click.prompt("GitHub username")
        token = click.prompt("Paste a GitHub token", hide_input=True)
        ref_name = render_name(cfg.secret_naming.default, profile=profile_name, service="github", kind="token")
        ref = backend.put(ref_name, token.encode("utf-8"))
        prof = cfg.profiles.get(profile_name) or Profile(name=profile_name)
        prof.github = GitHubService(username=username, host=host, token_ref=ref)
        cfg.profiles[profile_name] = prof
        save_config(cfg)
        click.echo(f"stored github token for {profile_name} at {ref}")
        return

    if service == "slack":
        if not workspace:
            raise click.ClickException("--workspace is required for --service slack")
        token = click.prompt("Paste a Slack user token (xoxp-...)", hide_input=True)
        ref_name = render_name(cfg.secret_naming.slack_token, profile=profile_name, workspace=workspace)
        ref = backend.put(ref_name, token.encode("utf-8"))
        prof = cfg.profiles.get(profile_name) or Profile(name=profile_name)
        prof.slack = [w for w in prof.slack if w.workspace != workspace]
        prof.slack.append(SlackWorkspace(workspace=workspace, team_id=None, user_token_ref=ref))
        cfg.profiles[profile_name] = prof
        save_config(cfg)
        click.echo(f"stored slack token for {profile_name}/{workspace} at {ref}")
        return

    if service == "google":
        email = email or click.prompt("Google account email")
        if not client_id:
            _print_oauth_client_hint(cfg)
            client_id = click.prompt("OAuth client ID")
        client_secret = click.prompt("OAuth client secret", hide_input=True)

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
        save_config(cfg)
        click.echo(f"stored google identity for {profile_name}")
        return


@main.command("use")
@click.argument("profile_name")
def use_cmd(profile_name: str) -> None:
    cfg = _require_config()
    prof = cfg.profiles.get(profile_name)
    if not prof:
        raise click.ClickException(f"profile {profile_name!r} not found")
    backend = load_backend(cfg.secrets_backend)
    bundle = build_env(prof, backend)
    sys.stdout.write(emit_use(bundle))


@main.command("unset")
def unset_cmd() -> None:
    sys.stdout.write(emit_unset())


@main.command("exec", context_settings={"ignore_unknown_options": True})
@click.argument("profile_name")
@click.argument("argv", nargs=-1, required=True)
def exec_cmd(profile_name: str, argv: tuple[str, ...]) -> None:
    cfg = _require_config()
    prof = cfg.profiles.get(profile_name)
    if not prof:
        raise click.ClickException(f"profile {profile_name!r} not found")
    backend = load_backend(cfg.secrets_backend)
    bundle = build_env(prof, backend)
    env = {**os.environ, **bundle.env}
    rc = subprocess.call(list(argv), env=env)
    sys.exit(rc)


@main.command("token")
@click.argument("service", type=click.Choice(["google"]))
def token_cmd(service: str) -> None:
    cfg = _require_config()
    name = os.environ.get("HAT_PROFILE")
    if not name:
        raise click.ClickException("HAT_PROFILE not set; run `eval \"$(hat use <profile>)\"` first")
    prof = cfg.profiles.get(name)
    if not prof or not prof.google:
        raise click.ClickException(f"profile {name!r} has no google identity")
    backend = load_backend(cfg.secrets_backend)
    g = prof.google
    client_secret = backend.get(g.oauth_client_secret_ref).decode("utf-8")
    refresh = backend.get(g.refresh_token_ref).decode("utf-8")
    access = exchange_refresh_token(
        client_id=g.oauth_client_id,
        client_secret=client_secret,
        refresh_token=refresh,
    )
    click.echo(access)


@main.command("logout")
@click.argument("profile_name")
@click.option("--service", type=click.Choice(["google", "github", "slack"]), required=True)
@click.option("--workspace", help="Slack workspace label (required for --service slack)")
def logout_cmd(profile_name: str, service: str, workspace: str | None) -> None:
    cfg = _require_config()
    prof = cfg.profiles.get(profile_name)
    if not prof:
        raise click.ClickException(f"profile {profile_name!r} not found")
    backend = load_backend(cfg.secrets_backend)
    if service == "github" and prof.github:
        backend.delete(prof.github.token_ref)
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
    save_config(cfg)
    click.echo(f"removed {service} from {profile_name}")


@main.command("doctor")
@click.option("--gc", is_flag=True, help="Sweep stale ephemeral files for dead PIDs")
def doctor_cmd(gc: bool) -> None:
    cfg = _require_config()
    backend = load_backend(cfg.secrets_backend)
    try:
        backend.health_check()
    except Exception as e:
        raise click.ClickException(f"backend health check failed: {e}")
    click.echo(f"backend ({cfg.secrets_backend.type}): OK")
    if gc:
        EphemeralStore.gc()
        click.echo("ephemeral GC: done")
