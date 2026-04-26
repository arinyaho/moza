from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from hat.backends.base import SecretsBackend
from hat.config import Profile
from hat.ephemeral import EphemeralStore


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
        if g.adc_ref and not g.gcloud_login_required:
            adc = backend.get(g.adc_ref)
            adc_path = store.write(profile=profile.name, kind="adc", data=adc)
            bundle.env["GOOGLE_APPLICATION_CREDENTIALS"] = str(adc_path)
            bundle.ephemeral_files.append(adc_path)

    if profile.github:
        token = backend.get(profile.github.token_ref).decode("utf-8").strip()
        bundle.env["GH_TOKEN"] = token

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

    return bundle
