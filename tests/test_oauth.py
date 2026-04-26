from unittest.mock import MagicMock

import pytest

from hat.oauth import google_installed_app_flow


def test_returns_refresh_token_from_creds(mocker):
    fake_creds = MagicMock()
    fake_creds.refresh_token = "refresh-abc"
    fake_flow = MagicMock()
    fake_flow.run_local_server.return_value = fake_creds

    mocker.patch(
        "hat.oauth.InstalledAppFlow.from_client_config",
        return_value=fake_flow,
    )
    rt = google_installed_app_flow(
        client_id="cid",
        client_secret="csec",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    assert rt == "refresh-abc"
    fake_flow.run_local_server.assert_called_once()
    args, kwargs = fake_flow.run_local_server.call_args
    assert kwargs.get("port") == 0


def test_raises_when_no_refresh_token(mocker):
    fake_creds = MagicMock()
    fake_creds.refresh_token = None
    fake_flow = MagicMock()
    fake_flow.run_local_server.return_value = fake_creds
    mocker.patch("hat.oauth.InstalledAppFlow.from_client_config", return_value=fake_flow)
    with pytest.raises(RuntimeError, match="refresh token"):
        google_installed_app_flow(client_id="c", client_secret="s", scopes=["x"])
