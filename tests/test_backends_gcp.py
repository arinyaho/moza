from unittest.mock import MagicMock

import pytest

from mien.backends.base import BackendUnauthorized, SecretNotFound
from mien.backends.gcp import GCPSecretManagerBackend


@pytest.fixture
def client(mocker):
    fake = MagicMock()
    mocker.patch("mien.backends.gcp.SecretManagerServiceClient", return_value=fake)
    return fake


def test_get_returns_payload(client):
    client.access_secret_version.return_value.payload.data = b"abcd"
    b = GCPSecretManagerBackend(project="proj")
    assert b.get("projects/proj/secrets/foo/versions/latest") == b"abcd"
    client.access_secret_version.assert_called_once_with(
        request={"name": "projects/proj/secrets/foo/versions/latest"}
    )


def test_get_not_found(client):
    from google.api_core import exceptions as gex
    client.access_secret_version.side_effect = gex.NotFound("nope")
    b = GCPSecretManagerBackend(project="proj")
    with pytest.raises(SecretNotFound):
        b.get("projects/proj/secrets/x/versions/latest")


def test_get_unauthorized(client):
    from google.api_core import exceptions as gex
    client.access_secret_version.side_effect = gex.PermissionDenied("denied")
    b = GCPSecretManagerBackend(project="proj")
    with pytest.raises(BackendUnauthorized):
        b.get("projects/proj/secrets/x/versions/latest")


def test_put_creates_secret_then_adds_version(client):
    from google.api_core import exceptions as gex
    client.get_secret.side_effect = gex.NotFound("first time")
    added = MagicMock()
    added.name = "projects/proj/secrets/foo/versions/1"
    client.add_secret_version.return_value = added

    b = GCPSecretManagerBackend(project="proj")
    ref = b.put("foo", b"hello")

    client.create_secret.assert_called_once()
    client.add_secret_version.assert_called_once_with(
        request={
            "parent": "projects/proj/secrets/foo",
            "payload": {"data": b"hello"},
        }
    )
    assert ref == "projects/proj/secrets/foo/versions/latest"


def test_put_existing_secret_just_adds_version(client):
    client.get_secret.return_value = MagicMock()
    added = MagicMock()
    added.name = "projects/proj/secrets/foo/versions/2"
    client.add_secret_version.return_value = added

    b = GCPSecretManagerBackend(project="proj")
    ref = b.put("foo", b"hello")

    client.create_secret.assert_not_called()
    assert ref == "projects/proj/secrets/foo/versions/latest"
