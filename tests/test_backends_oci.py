import base64
from unittest.mock import MagicMock

import pytest

from hat.backends.base import SecretNotFound
from hat.backends.oci import OCIVaultBackend


@pytest.fixture
def clients(mocker):
    fake_secrets = MagicMock()
    fake_vault = MagicMock()
    mocker.patch("hat.backends.oci.oci.config.from_file", return_value={"region": "ap-chuncheon-1"})
    mocker.patch("hat.backends.oci.SecretsClient", return_value=fake_secrets)
    mocker.patch("hat.backends.oci.VaultsClient", return_value=fake_vault)
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


def test_put_creates_and_returns_ocid(clients):
    _, vault = clients
    created = MagicMock()
    created.id = "ocid1.vaultsecret.oc1..new"
    vault.create_secret.return_value.data = created

    b = OCIVaultBackend(vault_ocid="v", compartment_ocid="c", region="r")
    ref = b.put("hat-personal-github-token", b"ghp_xxx")
    assert ref == "ocid1.vaultsecret.oc1..new"
    vault.create_secret.assert_called_once()
