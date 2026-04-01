"""
services/spotify.py

Spotify playlist search and sync.

Main entry point: sync_playlist()
  - Searches Spotify for each audio entry from songs.json
  - Creates the playlist if it doesn't exist
  - Adds only tracks not already in the playlist (idempotent)
  - Saves a checkpoint after each track so runs can be resumed on failure
  - Batch-adds found tracks at the end (Spotify supports 100 per request)

Retry logic is handled by spotify_backoff() in services/common.py.
"""

import os

from services.common import spotify_backoff, load_checkpoint, save_checkpoint, write_missing


def search_track(sp, artist, title, raw):
    """
    Searches Spotify for a track and returns its URI.

    Strategy:
      1. Try a precise search: track:{title} artist:{artist}
      2. Fall back to a raw text search using the full audio label

    Args:
        sp:     Authenticated Spotify client
        artist: Artist name (may be empty)
        title:  Song title
        raw:    Full original audio label (e.g. "Coldplay•Yellow") — used as fallback

    Returns:
        Spotify track URI (e.g. "spotify:track:ABC123") or "" if not found.
    """
    if artist and title:
        res = spotify_backoff(sp.search, f"track:{title} artist:{artist}", type="track", limit=1)
        items = res.get("tracks", {}).get("items", [])
        if items:
            return items[0]["uri"]

    # Fallback: search using the raw label with bullet replaced by space
    res = spotify_backoff(sp.search, raw.replace("•", " "), type="track", limit=1)
    items = res.get("tracks", {}).get("items", [])
    return items[0]["uri"] if items else ""


def sync_playlist(sp, entries, playlist_name, public, username, missing_path, playlist_id=None, checkpoint_dir="."):
    """
    Syncs a list of audio entries to a Spotify playlist.

    Checkpoint file: {checkpoint_dir}/spotify_checkpoint.json
    The checkpoint stores all found URIs, the playlist pointer, and the current index.
    On resume, it skips ahead to the next unprocessed entry.
    At the end, all found tracks are batch-added and the checkpoint is deleted.

    Args:
        sp:             Authenticated Spotify client
        entries:        List of (url, artist, title, raw) from parse_audio_entries()
        playlist_name:  Name for the playlist (created if not existing)
        public:         Whether to make the playlist public
        username:       Instagram handle (used for playlist description + defaults)
        missing_path:   Where to write tracks not found on Spotify
        playlist_id:    Existing playlist ID to add to (None = create or find by name)
        checkpoint_dir: Directory for the checkpoint file

    Returns:
        (playlist_url, tracks_added, missing_count)
    """
    if not playlist_name:
        playlist_name = f"IG Reels - {username}"

    cp_path = os.path.join(checkpoint_dir, "spotify_checkpoint.json")
    cp = load_checkpoint(cp_path)

    if cp:
        # Resume from where we left off
        print(f"  Resuming from checkpoint ({cp['tracks_found']} found, entry {cp['next_index'] + 1}/{len(entries)})")
        playlist_id = cp["playlist_id"]
        playlist_url = cp["playlist_url"]
        track_uris = cp["track_uris"]
        missing = cp["missing"]
        start_index = cp["next_index"]
    else:
        # Fresh start — find or create the playlist
        if playlist_id:
            playlist = spotify_backoff(sp.playlist, playlist_id)
        else:
            playlist = _find_playlist_by_name(sp, playlist_name)
            if not playlist:
                me = spotify_backoff(sp.me)
                playlist = spotify_backoff(
                    sp.user_playlist_create,
                    me["id"],
                    playlist_name,
                    public=public,
                    description=f"Auto-generated from Instagram reels for {username}.",
                )
        playlist_id = playlist["id"]
        playlist_url = playlist["external_urls"]["spotify"]
        track_uris = []
        missing = []
        start_index = 0

    # Fetch existing tracks to avoid adding duplicates
    existing_uris = _get_playlist_track_uris(sp, playlist_id)
    total = len(entries)

    for idx, (_, artist, title, raw) in enumerate(entries[start_index:], start=start_index):
        uri = search_track(sp, artist, title, raw)
        if uri and uri not in track_uris and uri not in existing_uris:
            track_uris.append(uri)
        elif not uri:
            missing.append(raw)

        # Save checkpoint after every track — ensures we can resume on any failure
        save_checkpoint(cp_path, {
            "playlist_id": playlist_id,
            "playlist_url": playlist_url,
            "track_uris": track_uris,
            "missing": missing,
            "next_index": idx + 1,
            "tracks_found": len(track_uris),
        })

        if (idx + 1) % 10 == 0 or (idx + 1) == total:
            print(f"Spotify search progress: {idx + 1}/{total}")

    # Batch-add all found tracks (Spotify allows up to 100 per request)
    for i in range(0, len(track_uris), 100):
        spotify_backoff(sp.playlist_add_items, playlist_id, track_uris[i:i + 100])

    # Clean up checkpoint on successful completion
    if os.path.exists(cp_path):
        os.remove(cp_path)

    write_missing(missing, missing_path)
    return playlist_url, len(track_uris), len(missing)


def _find_playlist_by_name(sp, name):
    """Paginates through the user's playlists to find one matching name. Returns None if not found."""
    offset = 0
    while True:
        page = spotify_backoff(sp.current_user_playlists, limit=50, offset=offset)
        for pl in page.get("items", []):
            if pl.get("name") == name:
                return pl
        if not page.get("next"):
            break
        offset += 50
    return None


def _get_playlist_track_uris(sp, playlist_id):
    """Returns a set of all track URIs currently in the playlist (handles pagination)."""
    uris = set()
    offset = 0
    while True:
        page = spotify_backoff(
            sp.playlist_items,
            playlist_id,
            fields="items(track(uri)),next",
            limit=100,
            offset=offset,
        )
        for item in page.get("items", []):
            track = item.get("track") or {}
            uri = track.get("uri")
            if uri:
                uris.add(uri)
        if not page.get("next"):
            break
        offset += 100
    return uris
