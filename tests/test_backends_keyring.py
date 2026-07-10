from __future__ import annotations

import pytest
from keyring.errors import InitError, PasswordDeleteError

from moza.backends.base import BackendError, SecretNotFound
from moza.backends.keyring_store import KeyringBackend


@pytest.fixture
def kr(mocker):
    return mocker.patch("moza.backends.keyring_store.keyring")


def test_get_returns_bytes(kr):
    kr.get_password.return_value = "hunter2"
    b = KeyringBackend(service_prefix="moza-")
    assert b.get("moza-personal-github-token") == b"hunter2"
    kr.get_password.assert_called_once_with("moza-personal-github-token", "moza-personal-github-token")


def test_get_missing_raises(kr):
    kr.get_password.return_value = None
    b = KeyringBackend(service_prefix="moza-")
    with pytest.raises(SecretNotFound):
        b.get("nope")


def test_put_writes_and_returns_ref(kr):
    b = KeyringBackend(service_prefix="moza-")
    ref = b.put("moza-personal-google-refresh", b"refreshvalue")
    assert ref == "moza-personal-google-refresh"
    kr.set_password.assert_called_once_with(
        "moza-personal-google-refresh",
        "moza-personal-google-refresh",
        "refreshvalue",
    )


def test_delete_success(kr):
    b = KeyringBackend(service_prefix="moza-")
    b.delete("moza-personal-github-token")
    kr.delete_password.assert_called_once_with(
        "moza-personal-github-token", "moza-personal-github-token"
    )


def test_delete_missing_raises(kr):
    kr.delete_password.side_effect = PasswordDeleteError("not found")
    b = KeyringBackend(service_prefix="moza-")
    with pytest.raises(SecretNotFound):
        b.delete("nope")


def test_delete_backend_error_wraps(kr):
    kr.delete_password.side_effect = InitError("no keyring available")
    b = KeyringBackend(service_prefix="moza-")
    with pytest.raises(BackendError):
        b.delete("moza-personal-github-token")


def test_get_backend_error_wraps(kr):
    kr.get_password.side_effect = InitError("no keyring available")
    b = KeyringBackend(service_prefix="moza-")
    with pytest.raises(BackendError):
        b.get("moza-personal-github-token")


def test_put_backend_error_wraps(kr):
    kr.set_password.side_effect = InitError("no keyring available")
    b = KeyringBackend(service_prefix="moza-")
    with pytest.raises(BackendError):
        b.put("moza-personal-github-token", b"secret")


def test_list_returns_empty(kr):
    b = KeyringBackend(service_prefix="moza-")
    assert b.list(prefix="moza-personal") == []
