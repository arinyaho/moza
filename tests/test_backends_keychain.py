from unittest.mock import MagicMock

import pytest

from moza.backends.base import SecretNotFound
from moza.backends.keychain import MacOSKeychainBackend


@pytest.fixture
def runner(mocker):
    return mocker.patch("moza.backends.keychain._run")


def test_get_returns_bytes(runner):
    runner.return_value = (0, b"hunter2", b"")
    b = MacOSKeychainBackend(service_prefix="moza-")
    assert b.get("moza-personal-github-token") == b"hunter2"
    runner.assert_called_once()
    args = runner.call_args[0][0]
    assert args[:3] == ["security", "find-generic-password", "-w"]
    assert "-s" in args and "moza-personal-github-token" in args


def test_get_missing_raises(runner):
    runner.return_value = (44, b"", b"The specified item could not be found")
    b = MacOSKeychainBackend(service_prefix="moza-")
    with pytest.raises(SecretNotFound):
        b.get("nope")


def test_put_writes_and_returns_ref(runner):
    runner.return_value = (0, b"", b"")
    b = MacOSKeychainBackend(service_prefix="moza-")
    ref = b.put("moza-personal-google-refresh", b"refreshvalue")
    assert ref == "moza-personal-google-refresh"
    args = runner.call_args[0][0]
    assert args[:2] == ["security", "add-generic-password"]
    assert "-U" in args  # update if exists


def test_delete(runner):
    runner.return_value = (0, b"", b"")
    b = MacOSKeychainBackend(service_prefix="moza-")
    b.delete("moza-personal-github-token")
    args = runner.call_args[0][0]
    assert args[:2] == ["security", "delete-generic-password"]


def test_list_filters_by_prefix(runner):
    runner.return_value = (0, b"", b"")
    b = MacOSKeychainBackend(service_prefix="moza-")
    assert b.list(prefix="moza-personal") == []
