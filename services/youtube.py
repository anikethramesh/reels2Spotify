"""
services/youtube.py

YouTube playlist search and sync.

Main entry point: sync_playlist()
  - Searches YouTube for each audio entry from songs.json
  - Creates the playlist if it doesn't exist
  - Fetches existing playlist contents to skip duplicates
  - Saves a checkpoint after each track for resumption
  - Handles daily quota exhaustion gracefully — saves position and exits cleanly

YouTube Data API v3 quota costs:
  - search.list:          100 units
  - playlistItems.insert:  50 units
  - playlists.insert:      50 units
  - Default daily limit: 10,000 units → ~66 tracks per day

Retry/backoff/quota logic is handled by youtube_execute() in services/common.py.
"""

import os

from services.common import youtube_execute, load_checkpoint, save_checkpoint, write_missing


class QuotaExceededError(Exception):
    """Raised by youtube_execute() when the daily API quota is exhausted."""
    pass


def search_video(yt, artist, title, raw):
    """
    Searches YouTube for a video matching the given track and returns its video ID.

    Strategy:
      1. Search with videoCategoryId=10 (Music) for more accurate results
      2. Fall back to an uncategorized search if no music results are found

    Args:
        yt:     Authenticated YouTube API resource
        artist: Artist name (may be empty)
        title:  Song title
        raw:    Full original audio label — used to build the search query

    Returns:
        YouTube video ID string, or "" if not found.
    """
    query = f"{artist} {title}".strip() if artist and title else raw.replace("•", " ")
    try:
        # Try music category first
        res = youtube_execute(yt.search().list(q=query, part="id", type="video", videoCategoryId="10", maxResults=1))
        items = res.get("items", [])
        if items:
            return items[0]["id"]["videoId"]

        # Fallback: search without category restriction
        res = youtube_execute(yt.search().list(q=query, part="id", type="video", maxResults=1))
        items = res.get("items", [])
        return items[0]["id"]["videoId"] if items else ""
    except QuotaExceededError:
        raise  # Propagate quota errors — handled in sync_playlist()
    except Exception:
        return ""


def get_playlist_video_ids(yt, playlist_id):
    """
    Returns a set of all video IDs currently in the YouTube playlist.
    Used to avoid re-adding tracks that are already present.
    Handles pagination (YouTube returns max 50 items per page).
    """
    video_ids = set()
    next_page = None
    while True:
        res = youtube_execute(yt.playlistItems().list(
            part="snippet",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=next_page,
        ))
        for item in res.get("items", []):
            video_ids.add(item["snippet"]["resourceId"]["videoId"])
        next_page = res.get("nextPageToken")
        if not next_page:
            break
    return video_ids


def sync_playlist(yt, entries, playlist_name, public, username, missing_path, playlist_id=None, checkpoint_dir="."):
    """
    Syncs a list of audio entries to a YouTube playlist.

    Checkpoint file: {checkpoint_dir}/youtube_checkpoint_{playlist_name}.json
    The checkpoint stores playlist pointer, progress index, and running counts.

    If the daily quota runs out mid-run, the checkpoint is left in place and the
    function returns partial results with a message to re-run tomorrow.

    Args:
        yt:             Authenticated YouTube API resource
        entries:        List of (url, artist, title, raw) from parse_audio_entries()
        playlist_name:  Name for the playlist (created if not existing)
        public:         Whether to make the playlist public
        username:       Instagram handle (used for playlist description + defaults)
        missing_path:   Where to write tracks not found on YouTube
        playlist_id:    Existing playlist ID to add to (None = create new)
        checkpoint_dir: Directory for the checkpoint file

    Returns:
        (playlist_url, tracks_added, missing_count)
    """
    if not playlist_name:
        playlist_name = f"IG Reels - {username}"

    # Use a filesystem-safe name for the checkpoint file
    safe_name = playlist_name.replace(" ", "_").replace("/", "-")
    cp_path = os.path.join(checkpoint_dir, f"youtube_checkpoint_{safe_name}.json")
    cp = load_checkpoint(cp_path)

    if cp:
        # Resume from checkpoint
        print(f"  Resuming from checkpoint ({cp['tracks_added']} added, entry {cp['next_index'] + 1}/{len(entries)})")
        playlist_id = cp["playlist_id"]
        playlist_url = cp["playlist_url"]
        tracks_added = cp["tracks_added"]
        missing = cp["missing"]
        start_index = cp["next_index"]
    else:
        # Fresh start — create playlist if needed
        if not playlist_id:
            privacy = "public" if public else "private"
            playlist = youtube_execute(yt.playlists().insert(
                part="snippet,status",
                body={
                    "snippet": {
                        "title": playlist_name,
                        "description": f"Auto-generated from Instagram reels for {username}.",
                    },
                    "status": {"privacyStatus": privacy},
                },
            ))
            playlist_id = playlist["id"]
        playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
        tracks_added = 0
        missing = []
        start_index = 0

    # Fetch existing videos to skip duplicates
    print("  Fetching existing playlist contents...")
    existing_video_ids = get_playlist_video_ids(yt, playlist_id)
    if existing_video_ids:
        print(f"  {len(existing_video_ids)} videos already in playlist, will skip duplicates.")

    total = len(entries)
    try:
        for idx, (_, artist, title, raw) in enumerate(entries[start_index:], start=start_index):
            video_id = search_video(yt, artist, title, raw)

            if video_id and video_id not in existing_video_ids:
                youtube_execute(yt.playlistItems().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "playlistId": playlist_id,
                            "resourceId": {"kind": "youtube#video", "videoId": video_id},
                        }
                    },
                ))
                existing_video_ids.add(video_id)
                tracks_added += 1
            elif not video_id:
                missing.append(raw)

            # Save checkpoint after every track
            save_checkpoint(cp_path, {
                "playlist_id": playlist_id,
                "playlist_url": playlist_url,
                "tracks_added": tracks_added,
                "missing": missing,
                "next_index": idx + 1,
            })

            if (idx + 1) % 10 == 0 or (idx + 1) == total:
                print(f"  YouTube sync progress: {idx + 1}/{total}")

    except QuotaExceededError:
        # Daily quota exhausted — checkpoint is already saved, tell user to re-run tomorrow
        print(f"\n  Daily YouTube quota exhausted. Progress saved — re-run to continue from entry {idx + 1}/{total}.")
        write_missing(missing, missing_path)
        return playlist_url, tracks_added, len(missing)

    # Success — clean up checkpoint
    if os.path.exists(cp_path):
        os.remove(cp_path)

    write_missing(missing, missing_path)
    return playlist_url, tracks_added, len(missing)
