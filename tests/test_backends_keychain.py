import pytest

from moza.backends.base import SecretNotFound
from moza.backends.keychain import MacOSKeychainBackend


@pytest.fixture
def kc(mocker):
    """Mock the macOS Keyring instance the backend talks to in-process."""
    inst = mocker.MagicMock()
    mocker.patch("moza.backends.keychain._MacKeyring", return_value=inst)
    return inst


def test_get_returns_bytes(kc):
    kc.get_password.return_value = "hunter2"
    b = MacOSKeychainBackend(service_prefix="moza-")
    assert b.get("moza-personal-github-token") == b"hunter2"
    kc.get_password.assert_called_once_with(
        "moza-personal-github-token", "moza-personal-github-token")


def test_get_missing_raises(kc):
    kc.get_password.return_value = None
    b = MacOSKeychainBackend(service_prefix="moza-")
    with pytest.raises(SecretNotFound):
        b.get("nope")


def test_put_never_passes_the_secret_through_argv(kc):
    """The whole point of this backend change: the secret goes in-process to the
    Keychain API, never onto a subprocess command line where `ps` could read it.
    """
    b = MacOSKeychainBackend(service_prefix="moza-")
    ref = b.put("moza-personal-google-refresh", b"s3cr3t-refresh")
    assert ref == "moza-personal-google-refresh"
    kc.set_password.assert_called_once_with(
        "moza-personal-google-refresh", "moza-personal-google-refresh", "s3cr3t-refresh")


def test_backend_module_does_not_import_subprocess():
    """A structural guard: if the secret can't reach a subprocess, it can't reach
    argv. The module must not use subprocess at all for the credential path."""
    import moza.backends.keychain as mod
    assert not hasattr(mod, "subprocess"), \
        "keychain backend must not use subprocess — that is how the secret leaked to argv"


def test_delete(kc):
    b = MacOSKeychainBackend(service_prefix="moza-")
    b.delete("moza-personal-github-token")
    kc.delete_password.assert_called_once_with(
        "moza-personal-github-token", "moza-personal-github-token")


def test_delete_missing_raises(kc):
    from keyring.errors import PasswordDeleteError
    kc.delete_password.side_effect = PasswordDeleteError("not found")
    b = MacOSKeychainBackend(service_prefix="moza-")
    with pytest.raises(SecretNotFound):
        b.delete("gone")


def test_list_returns_empty(kc):
    b = MacOSKeychainBackend(service_prefix="moza-")
    assert b.list(prefix="moza-personal") == []
