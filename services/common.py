"""
services/common.py

Shared utilities used by both services/spotify.py and services/youtube.py:

  - parse_audio_entries() — parses Instagram audio labels into (url, artist, title, raw) tuples
  - load_checkpoint() / save_checkpoint() — checkpoint file I/O for mid-run resumption
  - write_missing() — writes tracks not found on a platform to a text file
  - spotify_backoff() — calls a spotipy function with exponential backoff on rate limits
  - youtube_execute() — executes a YouTube API request with backoff + quota error detection
"""

import json
import os
import random
import time


# ---------------------------------------------------------------------------
# Audio label parsing
# ---------------------------------------------------------------------------

def parse_audio_entries(audio_map):
    """
    Parses Instagram audio labels into structured entries for platform search.

    Filters out:
      - "Original audio" entries (user-recorded audio, no song to search)
      - "UNKNOWN" entries (scraper couldn't find the audio label)

    Instagram audio labels come in two formats:
      - "Artist•Song Title"  (most common)
      - "Artist - Song Title" (less common)
      - "Song Title"          (no artist, rare)

    Args:
        audio_map: List of (url, audio_label) tuples from get_reel_audio()

    Returns:
        List of (url, artist, title, raw_label) tuples ready for platform search.
    """
    entries = []
    for url, audio in audio_map:
        if not audio:
            continue

        # Check only the title portion for "original audio" — avoids false positives
        # where the username contains "original audio" (e.g. "dankfrankdrury original audio")
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


# ---------------------------------------------------------------------------
# Checkpoint I/O — used by both Spotify and YouTube sync to enable resumption
# ---------------------------------------------------------------------------

def load_checkpoint(path):
    """
    Loads a checkpoint file if it exists.
    Returns the checkpoint dict, or None if no checkpoint exists.
    """
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def save_checkpoint(path, data):
    """
    Saves checkpoint data to disk after each track is processed.
    This ensures that if the process is interrupted, the next run can
    resume from the last successfully processed track.
    """
    with open(path, "w") as f:
        json.dump(data, f)


def write_missing(missing, path):
    """Writes a list of unmatched audio labels to a text file for manual review."""
    if missing:
        with open(path, "w", encoding="utf-8") as f:
            for item in missing:
                f.write(item + "\n")


# ---------------------------------------------------------------------------
# Spotify retry wrapper
# ---------------------------------------------------------------------------

def spotify_backoff(fn, *args, max_retries=6, **kwargs):
    """
    Calls a spotipy function with exponential backoff on rate limits.

    Handles two failure modes:
      1. SpotifyException with http_status 429 — rate limited. Respects the
         Retry-After header if present, otherwise uses exponential backoff.
      2. Generic Exception — can occur due to urllib3 version mismatches when
         Spotify returns a rate limit response. Retries with backoff.

    Args:
        fn:          The spotipy method to call (e.g. sp.search)
        *args:       Positional arguments for fn
        max_retries: Maximum number of attempts before giving up
        **kwargs:    Keyword arguments for fn

    Returns:
        The return value of fn(*args, **kwargs)
    """
    import spotipy
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except spotipy.SpotifyException as e:
            if e.http_status == 429:
                # Use Retry-After header if available, otherwise exponential backoff
                retry_after = int(e.headers.get("Retry-After", 2 ** attempt)) if e.headers else 2 ** attempt
                wait = retry_after + random.uniform(0, 1)  # jitter to avoid thundering herd
                print(f"\n  Spotify rate limited, waiting {wait:.1f}s...", flush=True)
                time.sleep(wait)
            else:
                raise
        except Exception as e:
            if attempt < max_retries - 1:
                wait = (2 ** attempt) + random.uniform(0, 1)
                print(f"\n  Transient error ({type(e).__name__}), retrying in {wait:.1f}s...", flush=True)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Max retries exceeded")


# ---------------------------------------------------------------------------
# YouTube API request executor
# ---------------------------------------------------------------------------

def youtube_execute(request, max_retries=6):
    """
    Executes a YouTube API request with exponential backoff and quota detection.

    YouTube error handling is more complex than Spotify:
      - 403 quotaExceeded / dailyLimitExceeded: daily quota gone — stop immediately,
        save checkpoint, tell user to re-run tomorrow. Raises QuotaExceededError.
      - 403 rateLimitExceeded / userRateLimitExceeded: per-second limit — back off and retry
      - 409, 429, 500, 503: transient errors — back off and retry

    A 0.5s delay is added after every successful call to stay within per-second limits
    without hitting the rate limiter in the first place.

    Args:
        request:     A Google API Client request object (result of yt.something().method(...))
        max_retries: Maximum number of attempts before giving up

    Returns:
        The response dict from request.execute()

    Raises:
        QuotaExceededError: When the daily quota is exhausted (caller should checkpoint and stop)
    """
    from googleapiclient.errors import HttpError
    from services.youtube import QuotaExceededError

    _CALL_DELAY = 0.5  # seconds between API calls to stay under per-second rate limits

    for attempt in range(max_retries):
        try:
            result = request.execute()
            time.sleep(_CALL_DELAY)
            return result
        except HttpError as e:
            error_body = json.loads(e.content.decode()) if e.content else {}
            reasons = [
                err.get("reason", "")
                for err in error_body.get("error", {}).get("errors", [])
            ]
            if e.status_code == 403:
                if any(r in reasons for r in ("quotaExceeded", "dailyLimitExceeded")):
                    # Daily quota exhausted — no point retrying, signal caller to stop
                    raise QuotaExceededError()
                if any(r in reasons for r in ("rateLimitExceeded", "userRateLimitExceeded")):
                    if attempt < max_retries - 1:
                        wait = (2 ** attempt) + random.uniform(0, 1)
                        print(f"\n  Rate limited, waiting {wait:.1f}s...", flush=True)
                        time.sleep(wait)
                        continue
                raise
            if e.status_code in (409, 429, 500, 503) and attempt < max_retries - 1:
                wait = (2 ** attempt) + random.uniform(0, 1)
                print(f"\n  Transient error ({e.status_code}), retrying in {wait:.1f}s...", flush=True)
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("Max retries exceeded")
