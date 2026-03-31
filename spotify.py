import os
from datetime import datetime

from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth


def spotify_client(client_id, client_secret, redirect_uri, cache_path, allow_interactive=False):
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
        raise RuntimeError(f"SPOTIFY_AUTH_REQUIRED:{auth_url}")
    return Spotify(auth_manager=auth)


def parse_audio_entries(audio_map):
    entries = []
    for url, audio in audio_map:
        if not audio:
            continue
        title_part = audio.split("•", 1)[-1].strip().lower() if "•" in audio else audio.lower()
        if title_part == "original audio":
            continue
        if audio.strip().upper() == "UNKNOWN":
            continue

        artist = ""
        title = ""
        if "•" in audio:
            artist, title = [x.strip() for x in audio.split("•", 1)]
        elif " - " in audio:
            artist, title = [x.strip() for x in audio.split(" - ", 1)]
        else:
            title = audio.strip()

        entries.append((url, artist, title, audio.strip()))
    return entries


def search_track(sp, artist, title, raw):
    if artist and title:
        q = f"track:{title} artist:{artist}"
        res = sp.search(q, type="track", limit=1)
        items = res.get("tracks", {}).get("items", [])
        if items:
            return items[0]["uri"]

    q = raw.replace("•", " ")
    res = sp.search(q, type="track", limit=1)
    items = res.get("tracks", {}).get("items", [])
    if items:
        return items[0]["uri"]
    return ""


def create_playlist(
    sp,
    entries,
    playlist_name,
    public,
    username,
    missing_path="spotify_missing.txt",
):
    if not playlist_name:
        playlist_name = f"IG Reels - {username}"

    playlist = _find_playlist_by_name(sp, playlist_name)
    if not playlist:
        me = sp.me()
        user_id = me["id"]
        playlist = sp.user_playlist_create(
            user_id,
            playlist_name,
            public=public,
            description=f"Auto-generated from Instagram reels for {username}.",
        )

    playlist_id = playlist["id"]
    playlist_url = playlist["external_urls"]["spotify"]

    existing_uris = _get_playlist_track_uris(sp, playlist_id)

    track_uris = []
    missing = []
    total = len(entries)
    for idx, (_, artist, title, raw) in enumerate(entries, start=1):
        uri = search_track(sp, artist, title, raw)
        if uri and uri not in track_uris:
            track_uris.append(uri)
        else:
            missing.append(raw)
        if idx % 10 == 0 or idx == total:
            print(f"Spotify search progress: {idx}/{total}")

    new_uris = [u for u in track_uris if u not in existing_uris]
    for i in range(0, len(new_uris), 100):
        sp.playlist_add_items(playlist_id, new_uris[i:i + 100])

    if missing:
        with open(missing_path, "w", encoding="utf-8") as f:
            for item in missing:
                f.write(item + "\n")

    return playlist_url, len(new_uris), len(missing)


def _find_playlist_by_name(sp, name):
    offset = 0
    while True:
        page = sp.current_user_playlists(limit=50, offset=offset)
        for pl in page.get("items", []):
            if pl.get("name") == name:
                return pl
        if not page.get("next"):
            break
        offset += 50
    return None


def _get_playlist_track_uris(sp, playlist_id):
    uris = set()
    offset = 0
    while True:
        page = sp.playlist_items(
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
