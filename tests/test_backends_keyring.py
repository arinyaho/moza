from __future__ import annotations

import pytest
from keyring.errors import InitError, PasswordDeleteError

from mien.backends.base import BackendError, SecretNotFound
from mien.backends.keyring_store import KeyringBackend


@pytest.fixture
def kr(mocker):
    return mocker.patch("mien.backends.keyring_store.keyring")


def test_get_returns_bytes(kr):
    kr.get_password.return_value = "hunter2"
    b = KeyringBackend(service_prefix="mien-")
    assert b.get("mien-personal-github-token") == b"hunter2"
    kr.get_password.assert_called_once_with("mien-personal-github-token", "mien-personal-github-token")


def test_get_missing_raises(kr):
    kr.get_password.return_value = None
    b = KeyringBackend(service_prefix="mien-")
    with pytest.raises(SecretNotFound):
        b.get("nope")


def test_put_writes_and_returns_ref(kr):
    b = KeyringBackend(service_prefix="mien-")
    ref = b.put("mien-personal-google-refresh", b"refreshvalue")
    assert ref == "mien-personal-google-refresh"
    kr.set_password.assert_called_once_with(
        "mien-personal-google-refresh",
        "mien-personal-google-refresh",
        "refreshvalue",
    )


def test_delete_success(kr):
    b = KeyringBackend(service_prefix="mien-")
    b.delete("mien-personal-github-token")
    kr.delete_password.assert_called_once_with(
        "mien-personal-github-token", "mien-personal-github-token"
    )


def test_delete_missing_raises(kr):
    kr.delete_password.side_effect = PasswordDeleteError("not found")
    b = KeyringBackend(service_prefix="mien-")
    with pytest.raises(SecretNotFound):
        b.delete("nope")


def test_delete_backend_error_wraps(kr):
    kr.delete_password.side_effect = InitError("no keyring available")
    b = KeyringBackend(service_prefix="mien-")
    with pytest.raises(BackendError):
        b.delete("mien-personal-github-token")


def test_get_backend_error_wraps(kr):
    kr.get_password.side_effect = InitError("no keyring available")
    b = KeyringBackend(service_prefix="mien-")
    with pytest.raises(BackendError):
        b.get("mien-personal-github-token")


def test_put_backend_error_wraps(kr):
    kr.set_password.side_effect = InitError("no keyring available")
    b = KeyringBackend(service_prefix="mien-")
    with pytest.raises(BackendError):
        b.put("mien-personal-github-token", b"secret")


def test_list_returns_empty(kr):
    b = KeyringBackend(service_prefix="mien-")
    assert b.list(prefix="mien-personal") == []
