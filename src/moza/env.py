from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from moza.backends.base import SecretsBackend
from moza.config import Profile
from moza.ephemeral import EphemeralStore


@dataclass
class EnvBundle:
    profile_name: str
    env: dict[str, str] = field(default_factory=dict)
    ephemeral_files: list[Path] = field(default_factory=list)


def build_env(profile: Profile, backend: SecretsBackend, *, pid: int | None = None) -> EnvBundle:
    pid = pid if pid is not None else os.getpid()
    store = EphemeralStore(pid=pid)
    bundle = EnvBundle(profile_name=profile.name)
    bundle.env["HAT_PROFILE"] = profile.name
    bundle.env["HAT_EPHEMERAL_DIR"] = str(store.root)

    if profile.google:
        g = profile.google
        bundle.env["CLOUDSDK_ACTIVE_CONFIG_NAME"] = g.gcloud_config_name
        if g.default_project:
            bundle.env["CLOUDSDK_CORE_PROJECT"] = g.default_project
        if (
            g.refresh_token_ref
            and g.oauth_client_secret_ref
            and not g.gcloud_login_required
        ):
            refresh = backend.get(g.refresh_token_ref).decode("utf-8").strip()
            client_secret = backend.get(g.oauth_client_secret_ref).decode("utf-8").strip()
            adc_payload = json.dumps(
                {
                    "type": "authorized_user",
                    "client_id": g.oauth_client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh,
                }
            ).encode("utf-8")
            adc_path = store.write(profile=profile.name, kind="adc", data=adc_payload)
            bundle.env["GOOGLE_APPLICATION_CREDENTIALS"] = str(adc_path)
            bundle.ephemeral_files.append(adc_path)

    if profile.github:
        gh = profile.github
        if gh.token_ref:
            token = backend.get(gh.token_ref).decode("utf-8").strip()
            bundle.env["GH_TOKEN"] = token
        ssh_path: str | None = None
        if gh.ssh_key_ref:
            key_data = backend.get(gh.ssh_key_ref)
            ephemeral = store.write(profile=profile.name, kind="ssh_key", data=key_data)
            bundle.ephemeral_files.append(ephemeral)
            ssh_path = str(ephemeral)
        elif gh.ssh_key_path:
            ssh_path = gh.ssh_key_path
        if ssh_path:
            bundle.env["GIT_SSH_COMMAND"] = f"ssh -i {ssh_path} -o IdentitiesOnly=yes"

    if profile.slack:
        mapping = {
            ws.workspace: backend.get(ws.user_token_ref).decode("utf-8").strip()
            for ws in profile.slack
        }
        slack_path = store.write(
            profile=profile.name, kind="slack",
            data=json.dumps(mapping).encode("utf-8"),
        )
        bundle.env["HAT_SLACK_TOKENS"] = str(slack_path)
        bundle.ephemeral_files.append(slack_path)
        if len(mapping) == 1:
            (only,) = mapping.values()
            bundle.env["HAT_SLACK_DEFAULT_TOKEN"] = only

    if profile.aws:
        aws = profile.aws
        if aws.access_key_id_ref and aws.secret_access_key_ref:
            key_id = backend.get(aws.access_key_id_ref).decode("utf-8").strip()
            secret = backend.get(aws.secret_access_key_ref).decode("utf-8").strip()
            bundle.env["AWS_ACCESS_KEY_ID"] = key_id
            bundle.env["AWS_SECRET_ACCESS_KEY"] = secret
        if aws.profile:
            bundle.env["AWS_PROFILE"] = aws.profile
        if aws.region:
            bundle.env["AWS_DEFAULT_REGION"] = aws.region

    if profile.oci:
        oci = profile.oci
        if oci.profile:
            bundle.env["OCI_CLI_PROFILE"] = oci.profile
        if oci.config_file:
            bundle.env["OCI_CLI_CONFIG_FILE"] = oci.config_file

    if profile.atlassian:
        atl = profile.atlassian
        token = backend.get(atl.api_token_ref).decode("utf-8").strip()
        bundle.env["ATLASSIAN_EMAIL"] = atl.email
        bundle.env["ATLASSIAN_API_TOKEN"] = token
        bundle.env["ATLASSIAN_BASE_URL"] = atl.base_url

    return bundle
