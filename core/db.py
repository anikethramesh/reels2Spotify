"""
core/db.py

All file I/O for the instaDB per-profile store.

Directory layout:
  instaDB/
    {username}/
      songs.json          — ground truth: all reels ever scraped for this profile
      spotify_state.json  — Spotify playlist_id + url (gitignored)
      youtube_state.json  — YouTube playlist_id + url (gitignored)
      *_missing.txt       — tracks not found on a platform (gitignored)
      *_checkpoint.json   — mid-sync resume state (gitignored)

songs.json schema:
  [
    { "url": "https://www.instagram.com/.../reel/ABC/", "audio": "Artist•Song Title" },
    ...
  ]

state file schema:
  { "playlist_id": "...", "playlist_url": "https://..." }
"""

import json
import os

# Root directory for all profile data — relative to wherever main.py/api.py is run from
INSTA_DB = "instaDB"


def profile_dir(username):
    """Returns the path to the profile's directory, creating it if needed."""
    path = os.path.join(INSTA_DB, username)
    os.makedirs(path, exist_ok=True)
    return path


def songs_path(username):
    return os.path.join(profile_dir(username), "songs.json")


def service_state_path(username, service):
    """e.g. instaDB/amruthasrini/spotify_state.json"""
    return os.path.join(profile_dir(username), f"{service}_state.json")


def load_songs(username):
    """Returns list of song dicts from songs.json, or [] if none yet."""
    path = songs_path(username)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []


def save_songs(username, songs):
    """Writes the full songs list to songs.json."""
    with open(songs_path(username), "w") as f:
        json.dump(songs, f, indent=2)


def load_service_state(username, service):
    """Returns the state dict for a given service, or None if not yet synced."""
    path = service_state_path(username, service)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def save_service_state(username, service, playlist_id, playlist_url):
    """Persists the playlist pointer so future syncs add to the same playlist."""
    with open(service_state_path(username, service), "w") as f:
        json.dump({"playlist_id": playlist_id, "playlist_url": playlist_url}, f, indent=2)
