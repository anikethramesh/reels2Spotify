# reels2Spotify

Scrapes an Instagram profile's reels, extracts the audio/song labels, and syncs them to a Spotify or YouTube playlist. Supports incremental updates — only new reels are processed on subsequent runs.

---

## Project Structure

```
reels2Spotify/
├── main.py               # CLI entry point
├── api.py                # FastAPI server (POST /crawl, POST /sync)
├── credentials.json      # All secrets — never commit this
│
├── auth/                 # Authentication concerns
│   ├── config.py         # Reads credentials.json, exposes typed getters
│   ├── spotify_auth.py   # Builds the Spotify client (OAuth2)
│   └── youtube_auth.py   # Builds the YouTube client (OAuth2)
│
├── core/                 # Application logic
│   ├── scraper.py        # Playwright-based Instagram scraper
│   ├── pipeline.py       # Orchestrates crawl and sync workflows
│   └── db.py             # All instaDB file I/O (songs.json, state files)
│
├── services/             # Per-platform music integrations
│   ├── common.py         # Shared: retry/backoff, checkpoint I/O, audio parsing
│   ├── spotify.py        # Spotify playlist search and sync
│   └── youtube.py        # YouTube playlist search and sync
│
└── instaDB/              # Per-profile data (auto-created)
    └── {username}/
        ├── songs.json            # Ground truth — all reels + audio labels
        ├── spotify_state.json    # Spotify playlist pointer (gitignored)
        ├── youtube_state.json    # YouTube playlist pointer (gitignored)
        └── *_missing.txt         # Tracks not found on the platform (gitignored)
```

---

## How It Works

There are two independent steps:

### 1. Crawl
Scrapes the Instagram profile's reels page using a logged-in Playwright browser session. For each reel, it extracts the audio label (e.g. `Coldplay•Yellow`). Results are saved to `instaDB/{username}/songs.json`.

On subsequent runs, only new reels are scraped — the scraper stops early once it hits reels it has already seen.

### 2. Sync
Reads `songs.json`, parses the audio labels into artist/title pairs, searches the target platform, and adds found tracks to the playlist. If the playlist doesn't exist yet, it creates one. If it does, it only adds tracks that aren't already in it.

`songs.json` is the single source of truth. Both Spotify and YouTube sync from the same file independently.

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Set up credentials.json

Create `credentials.json` in the project root:

```json
{
  "spotify": {
    "client_id": "...",
    "client_secret": "...",
    "redirect_uri": "http://127.0.0.1:8888/callback"
  },
  "youtube": {
    "client_id": "...",
    "client_secret": "..."
  }
}
```

**Spotify**: Create an app at [Spotify Developer Dashboard](https://developer.spotify.com/dashboard). Add `http://127.0.0.1:8888/callback` as a redirect URI.

**YouTube**: Create a project in [Google Cloud Console](https://console.cloud.google.com), enable the YouTube Data API v3, and create an OAuth 2.0 client (Web application type). Add `http://localhost:8080` and `http://localhost:8080/` as authorized redirect URIs.

### 3. Log in to Instagram (one-time)

```bash
python auth/setup/instagram_login.py
```

A browser window opens. Log in manually, then press Enter. The session is saved to `ig_profile/` and reused on all future runs.

> If you move the project to a new machine, re-run this — browser sessions don't transfer between OS/browser engine combinations.

### 4. Log in to YouTube (one-time)

```bash
python auth/setup/youtube_login.py
```

Opens a browser for Google OAuth consent. Token is saved to `youtube_token_cache.json` and auto-refreshed on future runs.

**Spotify** authenticates on first `sync` run — it will print a URL to open in your browser.

---

## Usage

### CLI

**Most common usage** — scrape a profile and add songs to a playlist in one command:
```bash
python main.py --username some_user --action crawl-sync --service spotify
python main.py --username some_user --action crawl-sync --service youtube
```

**All actions:**
```bash
# 1. Just scrape reels and update songs.json (no playlist changes)
python main.py --username some_user --action crawl

# 2. Just sync songs.json to a playlist (skips scraping — useful if you already crawled)
python main.py --username some_user --action sync --service spotify
python main.py --username some_user --action sync --service youtube

# 3. Crawl then sync to one platform in one go
python main.py --username some_user --action crawl-sync --service spotify
python main.py --username some_user --action crawl-sync --service youtube

# 4. Sync songs.json to both Spotify and YouTube (no scraping)
python main.py --username some_user --action sync-all
```

**Optional flags** (work with any sync action):
```bash
# Make the playlist public
python main.py --username some_user --action crawl-sync --service spotify --playlist-public

# Custom playlist name
python main.py --username some_user --action crawl-sync --service spotify --playlist-name "My Reels Mix"
```

`--username` is required for every command — it determines which `instaDB/{username}/` profile is read and written.

### API Server

```bash
uvicorn api:app --reload
```

**POST /crawl**
```json
{ "username": "amruthasrini", "max_scrolls": 500 }
```

**POST /sync**
```json
{ "username": "amruthasrini", "service": "spotify", "playlist_name": "", "playlist_public": false }
```

---

## Data Flow

```
Instagram profile
       │
  [crawl action]
  core/scraper.py   ← uses ig_profile/ browser session
       │
  instaDB/{username}/songs.json   ← ground truth, one entry per reel
       │
  [sync action]
  services/common.py  ← parse_audio_entries() filters "Original audio" + "UNKNOWN"
       │
       ├── services/spotify.py  → Spotify playlist
       └── services/youtube.py  → YouTube playlist
```

---

## Resuming After Failures

Both Spotify and YouTube sync save a checkpoint file inside `instaDB/{username}/` after every track. If a run is interrupted (crash, quota exhaustion, rate limit), simply re-run the same command — it will pick up from where it left off.

The checkpoint is deleted on successful completion.

---

## YouTube Quota

The YouTube Data API has a **10,000 unit/day** limit per project. Cost breakdown:
- Search: 100 units
- Playlist insert: 50 units
- **~66 tracks maximum per day**

If the daily quota is exhausted mid-run, the script prints a message and saves its position. Re-run the next day and it continues automatically from the checkpoint.

To increase the quota, go to Google Cloud Console → IAM & Admin → Quotas and request an increase for the YouTube Data API v3.

---

## Adding a New Platform

1. Create `services/{platform}.py` with a `sync_playlist()` function matching the Spotify/YouTube signature
2. Create `auth/{platform}_auth.py` with a client factory function
3. Add credentials to `credentials.json` and a getter in `auth/config.py`
4. Add the platform branch to `core/pipeline.py → sync_pipeline()`
5. Add `--service {platform}` to the choices in `main.py`

---

## Key Files for Maintenance

| File | What to touch when... |
|---|---|
| `auth/config.py` | Adding a new credential or changing the credentials.json schema |
| `core/scraper.py` | Instagram changes its page layout or audio selectors break |
| `services/common.py` | Changing retry logic, checkpoint format, or audio label parsing |
| `services/spotify.py` | Spotify search or playlist logic changes |
| `services/youtube.py` | YouTube search or quota handling changes |
| `core/pipeline.py` | Adding a new action or changing the crawl/sync orchestration |
| `core/db.py` | Changing where or how profile data is stored |
