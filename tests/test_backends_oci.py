import base64
from unittest.mock import MagicMock

import pytest

from mien.backends.base import SecretNotFound
from mien.backends.oci import OCIVaultBackend


@pytest.fixture
def clients(mocker):
    fake_secrets = MagicMock()
    fake_vault = MagicMock()
    mocker.patch("mien.backends.oci.oci.config.from_file", return_value={"region": "ap-chuncheon-1"})
    mocker.patch("mien.backends.oci.SecretsClient", return_value=fake_secrets)
    mocker.patch("mien.backends.oci.VaultsClient", return_value=fake_vault)
    return fake_secrets, fake_vault


def test_get_decodes_base64_payload(clients):
    secrets, _ = clients
    payload = base64.b64encode(b"hello").decode()
    bundle = MagicMock()
    bundle.secret_bundle_content.content = payload
    secrets.get_secret_bundle.return_value.data = bundle

    b = OCIVaultBackend(
        vault_ocid="ocid1.vault.oc1..vault",
        compartment_ocid="ocid1.compartment.oc1..c",
        region="ap-chuncheon-1",
    )
    assert b.get("ocid1.vaultsecret.oc1..s") == b"hello"
    secrets.get_secret_bundle.assert_called_once()


def test_get_not_found(clients):
    secrets, _ = clients
    from oci.exceptions import ServiceError
    secrets.get_secret_bundle.side_effect = ServiceError(status=404, code="NotFound", headers={}, message="x")
    b = OCIVaultBackend(
        vault_ocid="v", compartment_ocid="c", region="r",
    )
    with pytest.raises(SecretNotFound):
        b.get("ocid1.vaultsecret.oc1..s")


def _summary(name, ocid, state="ACTIVE"):
    s = MagicMock()
    s.secret_name = name
    s.id = ocid
    s.lifecycle_state = state
    return s


def test_put_creates_when_absent(clients):
    _, vault = clients
    vault.list_secrets.return_value.data = []
    created = MagicMock()
    created.id = "ocid1.vaultsecret.oc1..new"
    vault.create_secret.return_value.data = created

    b = OCIVaultBackend(vault_ocid="v", compartment_ocid="c", region="r")
    ref = b.put("mien-personal-github-token", b"ghp_xxx")
    assert ref == "ocid1.vaultsecret.oc1..new"
    vault.create_secret.assert_called_once()
    vault.update_secret.assert_not_called()


def test_put_updates_existing_active_secret(clients):
    """The manifest is written under one fixed name on every push. A second push
    must add a version to the existing secret, not fail with a name conflict."""
    _, vault = clients
    existing = _summary("mien-config-manifest", "ocid1.vaultsecret.oc1..existing")
    vault.list_secrets.return_value.data = [existing]
    vault.update_secret.return_value.data = existing

    b = OCIVaultBackend(vault_ocid="v", compartment_ocid="c", region="r")
    ref = b.put("mien-config-manifest", b"new-manifest")
    assert ref == "ocid1.vaultsecret.oc1..existing"
    vault.update_secret.assert_called_once()
    # secret_id must be the existing OCID, and the new content must be carried.
    kw = vault.update_secret.call_args.kwargs
    assert kw["secret_id"] == "ocid1.vaultsecret.oc1..existing"
    import base64 as _b64
    content = kw["update_secret_details"].secret_content.content
    assert _b64.b64decode(content) == b"new-manifest"
    vault.create_secret.assert_not_called()


def test_put_reactivates_a_secret_scheduled_for_deletion(clients, mocker):
    """`mien logout` schedules deletion; a later `mien login` for the same name
    must cancel that and update, not create a colliding name. Cancellation is an
    async transition, so the secret must reach ACTIVE before update_secret, which
    the SDK rejects on a non-ACTIVE secret — so a wait sits between them."""
    _, vault = clients
    wait = mocker.patch("mien.backends.oci.oci.wait_until")
    pending = _summary("mien-personal-github-token",
                       "ocid1.vaultsecret.oc1..pending", state="PENDING_DELETION")
    vault.list_secrets.return_value.data = [pending]
    vault.update_secret.return_value.data = pending

    b = OCIVaultBackend(vault_ocid="v", compartment_ocid="c", region="r")
    ref = b.put("mien-personal-github-token", b"ghp_new")
    assert ref == "ocid1.vaultsecret.oc1..pending"

    vault.cancel_secret_deletion.assert_called_once_with(
        secret_id="ocid1.vaultsecret.oc1..pending")
    # The wait for ACTIVE must happen after cancel and before update.
    wait.assert_called_once()
    assert wait.call_args.args[2] == "lifecycle_state"
    assert wait.call_args.args[3] == "ACTIVE"
    vault.update_secret.assert_called_once()
    vault.create_secret.assert_not_called()


def test_put_waits_before_update_when_already_cancelling(clients, mocker):
    """A secret already mid-cancel must not be cancelled again — that is a 409 on
    a secret not pending deletion — but it still needs the wait before update."""
    _, vault = clients
    wait = mocker.patch("mien.backends.oci.oci.wait_until")
    cancelling = _summary("mien-personal-github-token",
                          "ocid1.vaultsecret.oc1..canc", state="CANCELLING_DELETION")
    vault.list_secrets.return_value.data = [cancelling]
    vault.update_secret.return_value.data = cancelling

    b = OCIVaultBackend(vault_ocid="v", compartment_ocid="c", region="r")
    b.put("mien-personal-github-token", b"ghp_new")

    vault.cancel_secret_deletion.assert_not_called()
    wait.assert_called_once()
    vault.update_secret.assert_called_once()


def test_put_ignores_a_deleted_namesake_and_creates(clients):
    """A fully DELETED secret of the same name is gone; put must create a fresh
    one rather than try to update a tombstone."""
    _, vault = clients
    dead = _summary("mien-config-manifest", "ocid1.vaultsecret.oc1..dead",
                    state="DELETED")
    vault.list_secrets.return_value.data = [dead]
    created = MagicMock()
    created.id = "ocid1.vaultsecret.oc1..fresh"
    vault.create_secret.return_value.data = created

    b = OCIVaultBackend(vault_ocid="v", compartment_ocid="c", region="r")
    ref = b.put("mien-config-manifest", b"m")
    assert ref == "ocid1.vaultsecret.oc1..fresh"
    vault.create_secret.assert_called_once()
    vault.update_secret.assert_not_called()
