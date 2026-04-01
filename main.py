"""
main.py

CLI entry point for reels2Spotify.

Actions:
  crawl               — scrape reels, update songs.json
  sync                — sync songs.json to one platform (--service spotify|youtube)
  crawl-sync          — crawl then immediately sync to one platform (--service spotify|youtube)
  sync-all            — sync songs.json to both Spotify and YouTube

Usage:
  python main.py --username some_user --action crawl
  python main.py --username some_user --action sync --service spotify
  python main.py --username some_user --action sync --service youtube
  python main.py --username some_user --action crawl-sync --service spotify
  python main.py --username some_user --action crawl-sync --service youtube
  python main.py --username some_user --action sync-all
  python main.py --username some_user --action sync --service spotify --playlist-public

--username is required. It determines which instaDB/{username}/ profile is read/written.

See README.md for full setup and usage instructions.
"""

import argparse

from core.pipeline import crawl_pipeline, sync_pipeline


def _parse_args():
    parser = argparse.ArgumentParser(description="Sync Instagram reels audio to Spotify or YouTube")
    parser.add_argument(
        "--username",
        required=True,
        help="Instagram username to scrape / sync",
    )
    parser.add_argument(
        "--action",
        choices=["crawl", "sync", "crawl-sync", "sync-all"],
        default="crawl",
        help=(
            "crawl: scrape reels and update songs.json | "
            "sync: push songs.json to one platform | "
            "crawl-sync: crawl then sync to one platform | "
            "sync-all: sync to both Spotify and YouTube"
        ),
    )
    parser.add_argument(
        "--service",
        choices=["spotify", "youtube"],
        default="spotify",
        help="Platform to sync to — used with --action sync and crawl-sync (ignored for sync-all)",
    )
    parser.add_argument(
        "--max-scrolls",
        type=int,
        default=500,
        help="Max scroll iterations when crawling (safety cap, stagnation logic exits sooner)",
    )
    parser.add_argument("--playlist-name", default="", help="Custom playlist name (default: 'IG Reels - {username}')")
    parser.add_argument("--playlist-public", action="store_true", help="Make the playlist public")
    return parser.parse_args()


def _sync(args, service):
    """Run sync_pipeline for a single service, handling auth errors gracefully."""
    try:
        result = sync_pipeline(
            username=args.username,
            service=service,
            playlist_name=args.playlist_name,
            playlist_public=args.playlist_public,
            allow_interactive=False,  # CLI doesn't open browser — prints URL instead
        )
        print(result)
    except RuntimeError as e:
        msg = str(e)
        if msg.startswith("YOUTUBE_AUTH_REQUIRED:"):
            print("YouTube authorization required. Open this URL in your browser:")
            print(msg.split(":", 1)[1])
        elif msg.startswith("SPOTIFY_AUTH_REQUIRED:"):
            print("Spotify authorization required. Open this URL in your browser:")
            print(msg.split(":", 1)[1])
        else:
            raise


def _main():
    args = _parse_args()

    if args.action == "crawl":
        result = crawl_pipeline(username=args.username, max_scrolls=args.max_scrolls)
        print(result)

    elif args.action == "sync":
        _sync(args, args.service)

    elif args.action == "crawl-sync":
        result = crawl_pipeline(username=args.username, max_scrolls=args.max_scrolls)
        print(result)
        if result["total_reels"] == 0:
            print("No reels in songs.json — skipping sync.")
        else:
            _sync(args, args.service)

    elif args.action == "sync-all":
        print("--- Syncing Spotify ---")
        _sync(args, "spotify")
        print("--- Syncing YouTube ---")
        _sync(args, "youtube")


if __name__ == "__main__":
    _main()
