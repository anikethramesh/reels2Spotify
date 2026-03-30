import argparse
import json
import asyncio

from pipeline import run_pipeline


CREDS = json.load(open("credentials.json"))


def _parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--username",
        default=CREDS.get("instagram", {}).get("target_username", ""),
        help="Instagram username to scrape",
    )
    parser.add_argument("--max-scrolls", type=int, default=25)
    parser.add_argument("--playlist-name", default="")
    parser.add_argument("--playlist-public", action="store_true")
    return parser.parse_args()


async def _main():
    args = _parse_args()
    if not args.username:
        raise SystemExit("Missing --username and no default target_username in credentials.json")
    try:
        result = await run_pipeline(
            username=args.username,
            max_scrolls=args.max_scrolls,
            playlist_name=args.playlist_name,
            playlist_public=args.playlist_public,
            allow_interactive=False,
        )
        print(result)
    except RuntimeError as e:
        msg = str(e)
        if msg.startswith("SPOTIFY_AUTH_REQUIRED:"):
            print("Spotify authorization required. Open this URL in your browser:")
            print(msg.split(":", 1)[1])
            return
        raise


if __name__ == "__main__":
    asyncio.run(_main())
