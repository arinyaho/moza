from __future__ import annotations

from google_auth_oauthlib.flow import InstalledAppFlow


def google_installed_app_flow(*, client_id: str, client_secret: str, scopes: list[str]) -> str:
    cfg = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(cfg, scopes=scopes)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    if not creds.refresh_token:
        raise RuntimeError(
            "OAuth completed but no refresh token was returned. "
            "Re-run with prompt=consent and ensure access_type=offline."
        )
    return creds.refresh_token


def exchange_refresh_token(*, client_id: str, client_secret: str, refresh_token: str) -> str:
    """Exchange refresh token for an access token."""
    import httpx

    resp = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]
