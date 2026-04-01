"""
core/pipeline.py

Orchestrates the two main workflows:

  crawl_pipeline() — scrapes Instagram reels and updates songs.json
  sync_pipeline()  — reads songs.json and syncs to a Spotify or YouTube playlist

These are the functions called by main.py (CLI) and api.py (FastAPI server).
Both are synchronous — Playwright's sync API is used throughout.

Design:
  - crawl and sync are intentionally decoupled. You can crawl once and sync
    to multiple services without re-crawling.
  - songs.json is the single source of truth. Service state files only store
    the playlist pointer (id + url).
"""

import os

from core.scraper import scrape_reels, get_reel_audio
from core.db import load_songs, save_songs, load_service_state, save_service_state, profile_dir
from auth.config import spotify_config, youtube_config
from auth.spotify_auth import spotify_client
from services.common import parse_audio_entries
from services.spotify import sync_playlist as spotify_sync_playlist


def crawl_pipeline(username, max_scrolls=500):
    """
    Scrapes an Instagram profile's reels and updates songs.json.

    Handles both first-time crawls and incremental updates:
    - First crawl: scrapes everything, creates songs.json
    - Subsequent crawls: only scrapes reels not already in songs.json,
      stops early once it hits previously-seen content

    Args:
        username:    Instagram handle to scrape
        max_scrolls: Hard cap on scroll iterations (safety net for huge profiles)

    Returns:
        { "new_reels": int, "total_reels": int }
    """
    existing = load_songs(username)
    known_urls = {s["url"] for s in existing}

    if known_urls:
        print(f"Scraping {username} for new reels ({len(existing)} already known)...")
    else:
        print(f"Scraping {username} (first crawl)...")

    links = scrape_reels(username, max_scrolls=max_scrolls, known_urls=known_urls)

    if not links:
        print("No new reels found. songs.json is up to date.")
        return {"new_reels": 0, "total_reels": len(existing)}

    print(f"Extracting audio labels for {len(links)} new reels...")
    audio_map = get_reel_audio(links)
    print()

    # Append new entries to existing songs (don't overwrite — preserve history)
    new_songs = [{"url": url, "audio": audio} for url, audio in audio_map]
    all_songs = existing + new_songs
    save_songs(username, all_songs)
    print(f"songs.json updated: {len(existing)} → {len(all_songs)} reels")
    return {"new_reels": len(new_songs), "total_reels": len(all_songs)}


def sync_pipeline(
    username,
    service="spotify",
    playlist_name="",
    playlist_public=False,
    allow_interactive=False,
):
    """
    Reads songs.json and syncs it to a Spotify or YouTube playlist.

    - If the playlist doesn't exist yet: creates it and adds all tracks
    - If the playlist already exists: only adds tracks not already in it
    - Resumes from checkpoint if a previous run was interrupted

    Both services check for duplicates against the live playlist contents,
    so re-running is always safe.

    Args:
        username:         Instagram handle (used to find songs.json and state files)
        service:          "spotify" or "youtube"
        playlist_name:    Custom name; defaults to "IG Reels - {username}"
        playlist_public:  Whether to make the playlist public
        allow_interactive: If True, opens browser for first-time OAuth. Should be
                          False in API mode (raises RuntimeError with auth URL instead).

    Returns:
        { "playlist_url": str, "tracks_added": int, "missing_count": int }
    """
    songs = load_songs(username)
    if not songs:
        raise RuntimeError(f"No songs.json found for {username}. Run --action crawl first.")

    # Filter out "Original audio" and "UNKNOWN" entries — only searchable tracks
    entries = parse_audio_entries([(s["url"], s["audio"]) for s in songs])
    print(f"Syncing {len(entries)} searchable tracks to {service}...")

    # Load existing playlist pointer if we've synced before
    state = load_service_state(username, service)
    existing_playlist_id = state["playlist_id"] if state else None
    pdir = profile_dir(username)

    if service == "youtube":
        # Lazy import — only load google libraries when actually needed
        from auth.youtube_auth import youtube_client
        from services.youtube import sync_playlist as yt_sync

        client_id, client_secret = youtube_config()
        yt = youtube_client(
            client_id=client_id,
            client_secret=client_secret,
            cache_path="youtube_token_cache.json",
            allow_interactive=allow_interactive,
        )
        playlist_url, tracks_added, missing_count = yt_sync(
            yt,
            entries,
            playlist_name=playlist_name,
            public=playlist_public,
            username=username,
            missing_path=os.path.join(pdir, "youtube_missing.txt"),
            playlist_id=existing_playlist_id,
            checkpoint_dir=pdir,
        )
    else:
        client_id, client_secret, redirect_uri = spotify_config()
        sp = spotify_client(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            cache_path="spotify_token_cache.json",
            allow_interactive=allow_interactive,
        )
        playlist_url, tracks_added, missing_count = spotify_sync_playlist(
            sp,
            entries,
            playlist_name=playlist_name,
            public=playlist_public,
            username=username,
            missing_path=os.path.join(pdir, "spotify_missing.txt"),
            playlist_id=existing_playlist_id,
            checkpoint_dir=pdir,
        )

    # Extract the playlist ID from the URL if this was a first-time sync
    if not existing_playlist_id:
        # YouTube: https://www.youtube.com/playlist?list=ID
        # Spotify:  https://open.spotify.com/playlist/ID
        playlist_id = playlist_url.split("?list=")[-1] if "?list=" in playlist_url else playlist_url.rstrip("/").split("/")[-1]
    else:
        playlist_id = existing_playlist_id

    # Persist the playlist pointer for future syncs
    save_service_state(username, service, playlist_id, playlist_url)

    return {
        "playlist_url": playlist_url,
        "tracks_added": tracks_added,
        "missing_count": missing_count,
    }
