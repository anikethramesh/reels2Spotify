from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from pipeline import run_pipeline


app = FastAPI(title="Reel2Spotify")


class PlaylistRequest(BaseModel):
    username: str


class PlaylistResponse(BaseModel):
    playlist_url: str
    tracks_added: int
    missing_count: int


@app.post("/playlist", response_model=PlaylistResponse)
async def create_playlist(req: PlaylistRequest):
    try:
        result = await run_pipeline(username=req.username, allow_interactive=False)
        return result
    except RuntimeError as e:
        msg = str(e)
        if msg.startswith("SPOTIFY_AUTH_REQUIRED:"):
            raise HTTPException(status_code=400, detail=msg)
        raise HTTPException(status_code=500, detail=msg)
