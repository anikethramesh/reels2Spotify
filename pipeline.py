import json
import os

from scraper import scrape_reels, get_reel_audio
from spotify import spotify_client, parse_audio_entries, create_playlist


CREDS = json.load(open("credentials.json"))


def _spotify_config():
    cfg = CREDS.get("spotify", {})
    client_id = cfg.get("client_id")
    client_secret = cfg.get("client_secret")
    redirect_uri = cfg.get("redirect_uri", "http://127.0.0.1:8888/callback")
    if not client_id or not client_secret:
        raise RuntimeError("Missing Spotify client_id/client_secret in credentials.json")
    return client_id, client_secret, redirect_uri


async def run_pipeline(
    username,
    max_scrolls=25,
    playlist_name="",
    playlist_public=False,
    allow_interactive=False,
    reels_audio_path="reels_audio.txt",
):
    print(f"Scraping reels for {username}...")
    links = await scrape_reels(username, max_scrolls=max_scrolls)
    print(f"Found {len(links)} reels. Extracting audio labels...")
    audio_map = await get_reel_audio(links)
    print(f"Extracted audio labels for {len(audio_map)} reels.")

    with open(reels_audio_path, "w", encoding="utf-8") as f:
        for url, audio in audio_map:
            f.write(f"{url}  |  {audio}\n")

    entries = parse_audio_entries(audio_map)
    print(f"Searchable audio labels: {len(entries)}")

    client_id, client_secret, redirect_uri = _spotify_config()
    sp = spotify_client(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        cache_path="spotify_token_cache.json",
        allow_interactive=allow_interactive,
    )

    print("Creating Spotify playlist...")
    playlist_url, tracks_added, missing_count = create_playlist(
        sp,
        entries,
        playlist_name=playlist_name,
        public=playlist_public,
        username=username,
        missing_path="spotify_missing.txt",
    )

    return {
        "playlist_url": playlist_url,
        "tracks_added": tracks_added,
        "missing_count": missing_count,
    }
