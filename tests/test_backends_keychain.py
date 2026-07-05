from unittest.mock import MagicMock

import pytest

from moza.backends.base import SecretNotFound
from moza.backends.keychain import MacOSKeychainBackend


@pytest.fixture
def runner(mocker):
    return mocker.patch("moza.backends.keychain._run")


def test_get_returns_bytes(runner):
    runner.return_value = (0, b"hunter2", b"")
    b = MacOSKeychainBackend(service_prefix="hat-")
    assert b.get("hat-personal-github-token") == b"hunter2"
    runner.assert_called_once()
    args = runner.call_args[0][0]
    assert args[:3] == ["security", "find-generic-password", "-w"]
    assert "-s" in args and "hat-personal-github-token" in args


def test_get_missing_raises(runner):
    runner.return_value = (44, b"", b"The specified item could not be found")
    b = MacOSKeychainBackend(service_prefix="hat-")
    with pytest.raises(SecretNotFound):
        b.get("nope")


def test_put_writes_and_returns_ref(runner):
    runner.return_value = (0, b"", b"")
    b = MacOSKeychainBackend(service_prefix="hat-")
    ref = b.put("hat-personal-google-refresh", b"refreshvalue")
    assert ref == "hat-personal-google-refresh"
    args = runner.call_args[0][0]
    assert args[:2] == ["security", "add-generic-password"]
    assert "-U" in args  # update if exists


def test_delete(runner):
    runner.return_value = (0, b"", b"")
    b = MacOSKeychainBackend(service_prefix="hat-")
    b.delete("hat-personal-github-token")
    args = runner.call_args[0][0]
    assert args[:2] == ["security", "delete-generic-password"]


def test_list_filters_by_prefix(runner):
    runner.return_value = (0, b"", b"")
    b = MacOSKeychainBackend(service_prefix="hat-")
    assert b.list(prefix="hat-personal") == []
