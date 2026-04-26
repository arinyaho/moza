from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

from hat.config import (
    BackendConfig,
    Config,
    SecretNaming,
    config_path,
    load_config,
    save_config,
)


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
