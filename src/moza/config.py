from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1


@dataclass
class BackendConfig:
    type: str
    options: dict = field(default_factory=dict)


@dataclass
class SecretNaming:
    default: str
    slack_token: str


@dataclass
class GoogleService:
    email: str
    oauth_client_id: str
    oauth_client_secret_ref: str | None
    refresh_token_ref: str
    adc_ref: str | None
    gcloud_config_name: str
    default_project: str | None
    gcloud_login_required: bool = False


@dataclass
class GitHubService:
    username: str
    host: str
    token_ref: str | None = None
    ssh_key_path: str | None = None
    ssh_key_ref: str | None = None


@dataclass
class SlackWorkspace:
    workspace: str
    team_id: str | None
    user_token_ref: str


@dataclass
class AWSService:
    region: str | None = None
    profile: str | None = None
    access_key_id_ref: str | None = None
    secret_access_key_ref: str | None = None


@dataclass
class OCIService:
    profile: str | None = None
    config_file: str | None = None


@dataclass
class AtlassianService:
    email: str
    base_url: str
    api_token_ref: str


@dataclass
class NotionService:
    api_token_ref: str


@dataclass
class ProjectEnvScope:
    match: str
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class Profile:
    name: str
    google: GoogleService | None = None
    github: GitHubService | None = None
    slack: list[SlackWorkspace] = field(default_factory=list)
    aws: AWSService | None = None
    oci: OCIService | None = None
    atlassian: AtlassianService | None = None
    notion: NotionService | None = None
    project_env: list[ProjectEnvScope] = field(default_factory=list)


@dataclass
class Config:
    schema_version: int
    secrets_backend: BackendConfig
    bootstrap: dict
    secret_naming: SecretNaming
    profiles: dict[str, Profile]


def config_path() -> Path:
    override = os.environ.get("MOZA_CONFIG")
    if override:
        return Path(override)
    home = Path(os.environ.get("HOME", str(Path.home())))
    return home / ".config" / "moza" / "config.json"


def serialize_config(cfg: Config) -> str:
    return json.dumps(_config_to_dict(cfg), indent=2, sort_keys=False)


def deserialize_config(raw: str | dict) -> Config:
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid config JSON: {exc}") from exc
    else:
        data = raw
    version = data.get("$schema_version", data.get("schema_version"))
    if version != SCHEMA_VERSION:
        raise ValueError(f"Unsupported schema_version {version!r}; expected {SCHEMA_VERSION}")
    return _config_from_dict(data)


def load_config() -> Config | None:
    path = config_path()
    if not path.exists():
        return None
    return deserialize_config(path.read_text())


def save_config(cfg: Config) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_config(cfg))
    path.chmod(0o600)


def _config_to_dict(cfg: Config) -> dict:
    profiles = {}
    for name, prof in cfg.profiles.items():
        profiles[name] = {
            "google": asdict(prof.google) if prof.google else None,
            "github": asdict(prof.github) if prof.github else None,
            "slack": [asdict(w) for w in prof.slack],
            "aws": asdict(prof.aws) if prof.aws else None,
            "oci": asdict(prof.oci) if prof.oci else None,
            "atlassian": asdict(prof.atlassian) if prof.atlassian else None,
            "notion": asdict(prof.notion) if prof.notion else None,
            "project_env": [asdict(s) for s in prof.project_env],
        }
    return {
        "$schema_version": cfg.schema_version,
        "secrets_backend": {"type": cfg.secrets_backend.type, **cfg.secrets_backend.options},
        "bootstrap": cfg.bootstrap,
        "secret_naming": asdict(cfg.secret_naming),
        "profiles": profiles,
    }


def _config_from_dict(raw: dict) -> Config:
    sb_raw = dict(raw.get("secrets_backend", {}))
    sb_type = sb_raw.pop("type")
    secrets_backend = BackendConfig(type=sb_type, options=sb_raw)

    sn = raw.get("secret_naming") or {}
    secret_naming = SecretNaming(
        default=sn.get("default", "moza-{profile}-{service}-{kind}"),
        slack_token=sn.get("slack_token", "moza-{profile}-slack-{workspace}-token"),
    )

    profiles: dict[str, Profile] = {}
    for name, p in (raw.get("profiles") or {}).items():
        google = GoogleService(**p["google"]) if p.get("google") else None
        github = GitHubService(**p["github"]) if p.get("github") else None
        slack = [SlackWorkspace(**w) for w in (p.get("slack") or [])]
        aws = AWSService(**p["aws"]) if p.get("aws") else None
        oci = OCIService(**p["oci"]) if p.get("oci") else None
        atlassian = AtlassianService(**p["atlassian"]) if p.get("atlassian") else None
        notion = NotionService(**p["notion"]) if p.get("notion") else None
        project_env = [
            ProjectEnvScope(match=s["match"], env=dict(s.get("env") or {}))
            for s in (p.get("project_env") or [])
        ]
        profiles[name] = Profile(
            name=name,
            google=google,
            github=github,
            slack=slack,
            aws=aws,
            oci=oci,
            atlassian=atlassian,
            notion=notion,
            project_env=project_env,
        )

    return Config(
        schema_version=SCHEMA_VERSION,
        secrets_backend=secrets_backend,
        bootstrap=raw.get("bootstrap") or {},
        secret_naming=secret_naming,
        profiles=profiles,
    )
