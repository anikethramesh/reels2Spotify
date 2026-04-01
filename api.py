"""
api.py

FastAPI server exposing the crawl and sync pipelines as HTTP endpoints.
Route handlers are sync (def, not async def) — FastAPI runs them in a thread pool,
which is appropriate since the pipeline does blocking I/O (Playwright, HTTP calls).

Start with:
  uvicorn api:app --reload

Endpoints:
  POST /crawl  — scrape an Instagram profile and update songs.json
  POST /sync   — sync songs.json to a Spotify or YouTube playlist

Authentication notes:
  - Spotify and YouTube tokens must be pre-authorized before calling /sync.
    Run the CLI once or use the login scripts to cache tokens.
  - A 401 response means the token is missing or expired.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from core.pipeline import crawl_pipeline, sync_pipeline


app = FastAPI(
    title="reels2Spotify",
    description="Sync Instagram reels audio to Spotify or YouTube playlists",
)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class CrawlRequest(BaseModel):
    username: str
    max_scrolls: int = 500  # Safety cap — stagnation logic exits sooner in practice


class SyncRequest(BaseModel):
    username: str
    service: str = "spotify"       # "spotify" or "youtube"
    playlist_name: str = ""        # Defaults to "IG Reels - {username}"
    playlist_public: bool = False


class CrawlResponse(BaseModel):
    new_reels: int     # Number of new reels found this run
    total_reels: int   # Total reels in songs.json after this run


class SyncResponse(BaseModel):
    playlist_url: str
    tracks_added: int    # Tracks added in this sync (excludes already-present tracks)
    missing_count: int   # Tracks searched but not found on the platform


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/crawl", response_model=CrawlResponse)
def crawl(req: CrawlRequest):
    """
    Scrape an Instagram profile's reels and update songs.json.

    Safe to call repeatedly — only new reels are processed each time.
    """
    try:
        return crawl_pipeline(username=req.username, max_scrolls=req.max_scrolls)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sync", response_model=SyncResponse)
def sync(req: SyncRequest):
    """
    Sync songs.json to a Spotify or YouTube playlist.

    Creates the playlist on first call, adds only missing tracks on subsequent calls.
    Requires pre-authorized OAuth tokens — returns 401 if authorization is needed.
    """
    if req.service not in ("spotify", "youtube"):
        raise HTTPException(status_code=400, detail="service must be 'spotify' or 'youtube'")
    try:
        return sync_pipeline(
            username=req.username,
            service=req.service,
            playlist_name=req.playlist_name,
            playlist_public=req.playlist_public,
            allow_interactive=False,  # API mode never opens a browser
        )
    except RuntimeError as e:
        msg = str(e)
        if "AUTH_REQUIRED" in msg:
            # Token missing or expired — user needs to re-authorize via CLI/login scripts
            raise HTTPException(status_code=401, detail=msg)
        raise HTTPException(status_code=500, detail=msg)
