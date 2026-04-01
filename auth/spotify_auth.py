"""
auth/spotify_auth.py

Builds and returns an authenticated Spotify client using spotipy's OAuth2 flow.

On first use (no cached token), raises RuntimeError with the authorization URL
so the caller can display it to the user. After the user visits the URL and
authorizes, the token is cached at cache_path and future runs authenticate silently.
"""

from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth


def spotify_client(client_id, client_secret, redirect_uri, cache_path, allow_interactive=False):
    """
    Returns an authenticated Spotify client.

    Args:
        client_id:        From Spotify Developer Dashboard
        client_secret:    From Spotify Developer Dashboard
        redirect_uri:     Must match what's registered in the Spotify app settings
        cache_path:       Where to store/read the OAuth token (e.g. spotify_token_cache.json)
        allow_interactive: If True, opens browser for auth flow. If False, raises RuntimeError
                          with the auth URL so the caller can handle it (used in CLI/API mode).
    """
    scope = "playlist-modify-private playlist-modify-public"
    auth = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=scope,
        cache_path=cache_path,
        open_browser=False,
    )

    if not auth.get_cached_token():
        auth_url = auth.get_authorize_url()
        if allow_interactive:
            return Spotify(auth_manager=auth)
        # Signal to the caller that they need to display this URL to the user
        raise RuntimeError(f"SPOTIFY_AUTH_REQUIRED:{auth_url}")

    return Spotify(auth_manager=auth)
