"""
auth/config.py

Single source of truth for reading credentials.json.
All other modules should import from here rather than opening credentials.json directly.

credentials.json schema:
{
  "spotify":   { "client_id": "...", "client_secret": "...", "redirect_uri": "..." },
  "youtube":   { "client_id": "...", "client_secret": "..." }
}
"""

import json
import os

# Resolve credentials.json relative to the project root (one level up from auth/)
_CREDS_PATH = os.path.join(os.path.dirname(__file__), "..", "credentials.json")

# Cached after first load so we don't re-read the file on every call
_creds = None


def _load():
    global _creds
    if _creds is None:
        with open(_CREDS_PATH) as f:
            _creds = json.load(f)
    return _creds


def spotify_config():
    """Returns (client_id, client_secret, redirect_uri) for Spotify OAuth."""
    cfg = _load().get("spotify", {})
    client_id = cfg.get("client_id")
    client_secret = cfg.get("client_secret")
    redirect_uri = cfg.get("redirect_uri", "http://127.0.0.1:8888/callback")
    if not client_id or not client_secret:
        raise RuntimeError("Missing Spotify client_id/client_secret in credentials.json")
    return client_id, client_secret, redirect_uri


def youtube_config():
    """Returns (client_id, client_secret) for YouTube OAuth."""
    cfg = _load().get("youtube", {})
    client_id = cfg.get("client_id")
    client_secret = cfg.get("client_secret")
    if not client_id or not client_secret:
        raise RuntimeError("Missing YouTube client_id/client_secret in credentials.json")
    return client_id, client_secret


