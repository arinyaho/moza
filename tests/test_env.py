import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hat.config import (
    GitHubService,
    GoogleService,
    Profile,
    SlackWorkspace,
)
from hat.env import build_env


@pytest.fixture
def fake_backend():
    b = MagicMock()
    b.get.side_effect = lambda ref: {
        "refresh-ref": b"refresh-tok",
        "csec-ref": b"client-secret-val",
        "gh-token-ref": b"ghp_xxx",
        "slack-team-a-ref": b"xoxp-aaa",
        "slack-team-b-ref": b"xoxp-bbb",
    }[ref]
    return b


def test_google_synthesizes_adc_from_refresh_token(monkeypatch, tmp_path, fake_backend):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    prof = Profile(
        name="personal",
        google=GoogleService(
            email="me@x.com",
            oauth_client_id="cid-123",
            oauth_client_secret_ref="csec-ref",
            refresh_token_ref="refresh-ref",
            adc_ref=None,
            gcloud_config_name="personal",
            default_project="myproj",
            gcloud_login_required=False,
        ),
    )
    bundle = build_env(prof, fake_backend, pid=111)
    env = bundle.env
    assert env["HAT_PROFILE"] == "personal"
    assert env["CLOUDSDK_ACTIVE_CONFIG_NAME"] == "personal"
    assert env["CLOUDSDK_CORE_PROJECT"] == "myproj"
    adc_path = Path(env["GOOGLE_APPLICATION_CREDENTIALS"])
    assert adc_path.exists()
    payload = json.loads(adc_path.read_text())
    assert payload == {
        "type": "authorized_user",
        "client_id": "cid-123",
        "client_secret": "client-secret-val",
        "refresh_token": "refresh-tok",
    }
    assert (adc_path.stat().st_mode & 0o777) == 0o600
    assert "GH_TOKEN" not in env
    assert "HAT_SLACK_TOKENS" not in env
    assert fake_backend.get.call_count == 2  # refresh_token_ref + oauth_client_secret_ref


def test_skips_adc_when_login_required(monkeypatch, tmp_path, fake_backend):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    prof = Profile(
        name="heaan",
        google=GoogleService(
            email="me@h.com",
            oauth_client_id="cid",
            oauth_client_secret_ref=None,
            refresh_token_ref="refresh-ref",
            adc_ref=None,
            gcloud_config_name="heaan",
            default_project="hp",
            gcloud_login_required=True,
        ),
    )
    bundle = build_env(prof, fake_backend, pid=222)
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in bundle.env
    fake_backend.get.assert_not_called()


def test_github_sets_gh_token(monkeypatch, tmp_path, fake_backend):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    prof = Profile(
        name="work",
        github=GitHubService(username="u", host="github.com", token_ref="gh-token-ref"),
    )
    bundle = build_env(prof, fake_backend, pid=333)
    assert bundle.env["GH_TOKEN"] == "ghp_xxx"


def test_github_ssh_key_path_sets_git_ssh_command(monkeypatch, tmp_path, fake_backend):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    prof = Profile(
        name="work",
        github=GitHubService(
            username="u", host="github.com", token_ref=None,
            ssh_key_path="/home/u/.ssh/id_work",
        ),
    )
    bundle = build_env(prof, fake_backend, pid=701)
    assert "GH_TOKEN" not in bundle.env
    assert bundle.env["GIT_SSH_COMMAND"] == "ssh -i /home/u/.ssh/id_work -o IdentitiesOnly=yes"


def test_github_ssh_key_ref_materializes_ephemeral_file(monkeypatch, tmp_path, fake_backend):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    fake_backend.get.side_effect = lambda ref: {"ssh-ref": b"PRIVATE-KEY-BYTES"}[ref]
    prof = Profile(
        name="work",
        github=GitHubService(
            username="u", host="github.com", token_ref=None,
            ssh_key_ref="ssh-ref",
        ),
    )
    bundle = build_env(prof, fake_backend, pid=702)
    cmd = bundle.env["GIT_SSH_COMMAND"]
    assert cmd.startswith("ssh -i ")
    assert cmd.endswith(" -o IdentitiesOnly=yes")
    key_path = Path(cmd.split(" ")[2])
    assert key_path.read_bytes() == b"PRIVATE-KEY-BYTES"
    assert (key_path.stat().st_mode & 0o777) == 0o600


def test_slack_writes_workspace_map(monkeypatch, tmp_path, fake_backend):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    prof = Profile(
        name="p",
        slack=[
            SlackWorkspace(workspace="team-a", team_id=None, user_token_ref="slack-team-a-ref"),
            SlackWorkspace(workspace="team-b", team_id="T2", user_token_ref="slack-team-b-ref"),
        ],
    )
    bundle = build_env(prof, fake_backend, pid=444)
    p = Path(bundle.env["HAT_SLACK_TOKENS"])
    payload = json.loads(p.read_text())
    assert payload == {"team-a": "xoxp-aaa", "team-b": "xoxp-bbb"}
    assert (p.stat().st_mode & 0o777) == 0o600
    prof2 = Profile(
        name="solo",
        slack=[SlackWorkspace(workspace="team-a", team_id=None, user_token_ref="slack-team-a-ref")],
    )
    b2 = build_env(prof2, fake_backend, pid=555)
    assert b2.env["HAT_SLACK_DEFAULT_TOKEN"] == "xoxp-aaa"
