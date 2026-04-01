"""
auth/youtube_auth.py

Builds and returns an authenticated YouTube API client using Google OAuth2.

Token is cached at cache_path after first authorization and auto-refreshed using
the refresh token on subsequent runs. On first use with no cached token, raises
RuntimeError with the authorization URL (non-interactive mode) or opens a local
browser server (interactive mode).

Note: YouTube OAuth requires a Web application client type in Google Cloud Console,
with http://localhost:8080 and http://localhost:8080/ registered as redirect URIs.
"""

import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Only need write access to manage playlists
SCOPES = ["https://www.googleapis.com/auth/youtube"]


def youtube_client(client_id, client_secret, cache_path, allow_interactive=False):
    """
    Returns an authenticated YouTube API resource object.

    Args:
        client_id:        From Google Cloud Console OAuth client
        client_secret:    From Google Cloud Console OAuth client
        cache_path:       Where to store/read the OAuth token (e.g. youtube_token_cache.json)
        allow_interactive: If True, opens local browser server on port 8080 for auth.
                          If False, raises RuntimeError with the auth URL.
    """
    creds = None

    # Load cached credentials if they exist
    if os.path.exists(cache_path):
        creds = Credentials.from_authorized_user_file(cache_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # Token expired but refresh token is available — refresh silently
            creds.refresh(Request())
        else:
            # No valid token — need full OAuth flow
            client_config = {
                "installed": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uris": ["http://localhost"],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            if not allow_interactive:
                auth_url, _ = flow.authorization_url(prompt="consent")
                raise RuntimeError(f"YOUTUBE_AUTH_REQUIRED:{auth_url}")
            # Opens browser on port 8080 — must be registered in Google Cloud Console
            creds = flow.run_local_server(port=8080)

        # Persist the new/refreshed token for next run
        with open(cache_path, "w") as f:
            f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)
