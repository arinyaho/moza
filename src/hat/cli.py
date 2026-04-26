from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

from hat.backends import load_backend
from hat.config import (
    BackendConfig,
    Config,
    GitHubService,
    Profile,
    SecretNaming,
    SlackWorkspace,
    config_path,
    load_config,
    save_config,
)
from hat.secret_naming import render_name


@click.group()
@click.version_option()
def main() -> None:
    """hat — multi-identity credential router."""


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
        project = click.prompt("GCP project ID")
        bootstrap_account = click.prompt("Bootstrap GCP account email")
        backend = BackendConfig(type="gcp_secret_manager", options={"project": project})
        bootstrap = {"gcp_account": bootstrap_account}
    elif choice == "2":
        vault_ocid = click.prompt("Vault OCID")
        compartment_ocid = click.prompt("Compartment OCID")
        region = click.prompt("Region", default="ap-chuncheon-1")
        backend = BackendConfig(
            type="oci_vault",
            options={"vault_ocid": vault_ocid, "compartment_ocid": compartment_ocid, "region": region},
        )
        bootstrap = {}
    else:
        prefix = click.prompt("Service prefix", default="hat-")
        backend = BackendConfig(type="macos_keychain", options={"service_prefix": prefix})
        bootstrap = {}

    cfg = Config(
        schema_version=1,
        secrets_backend=backend,
        bootstrap=bootstrap,
        secret_naming=SecretNaming(
            default="hat-{profile}-{service}-{kind}",
            slack_token="hat-{profile}-slack-{workspace}-token",
        ),
        profiles={},
    )
    save_config(cfg)
    click.echo(f"Wrote {config_path()}.")
    click.echo("Next: `hat login <profile> --service google|github|slack`")


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
        # Implemented in Task 13.
        raise click.ClickException("google login not yet implemented (see Task 13)")
