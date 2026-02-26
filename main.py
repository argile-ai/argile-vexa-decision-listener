"""Vexa Decision Listener - Real-time meeting intelligence service.

Subscribes to Vexa transcript streams and uses an LLM to detect
decisions, action items, and architecture statements in real-time.
"""

import asyncio
import logging
import os
import secrets

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sse_starlette.sse import EventSourceResponse

from config import TrackerConfig, get_config, reset_config, save_config
from listener import get_all_items, subscribe, unsubscribe

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

app = FastAPI(
    title="Vexa Decision Listener",
    description="Real-time meeting intelligence: detects decisions, action items, and architecture statements from live transcripts.",
    version="0.1.0",
)

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "https://meet.argile.ai").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY = os.getenv("API_KEY", "")
_bearer = HTTPBearer(auto_error=False)


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    token: str | None = Query(None),
) -> None:
    """Accept auth via Bearer header or ?token= query param (for EventSource)."""
    provided = (credentials.credentials if credentials else None) or token
    if not API_KEY or not provided or not secrets.compare_digest(provided, API_KEY):
        raise HTTPException(status_code=401, detail="Invalid API key")


# ── Config endpoints ───────────────────────────────────────────────


@app.get("/config", response_model=TrackerConfig, dependencies=[Depends(verify_api_key)])
async def get_tracker_config():
    return get_config()


@app.put("/config", response_model=TrackerConfig, dependencies=[Depends(verify_api_key)])
async def update_tracker_config(cfg: TrackerConfig):
    return save_config(cfg)


@app.post("/config/reset", response_model=TrackerConfig, dependencies=[Depends(verify_api_key)])
async def reset_tracker_config():
    return reset_config()


# ── Decisions endpoints ────────────────────────────────────────────


@app.get("/decisions/{meeting_id}/all", dependencies=[Depends(verify_api_key)])
async def get_decisions(meeting_id: str):
    items = get_all_items(meeting_id)
    return {"items": items}


@app.get("/decisions/{meeting_id}", dependencies=[Depends(verify_api_key)])
async def stream_decisions(meeting_id: str):
    """SSE stream of real-time decisions for a meeting."""
    q = subscribe(meeting_id)

    async def event_generator():
        try:
            while True:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield {"data": item}
                except asyncio.TimeoutError:
                    # Send keepalive comment
                    yield {"comment": "keepalive"}
        except asyncio.CancelledError:
            pass
        finally:
            unsubscribe(meeting_id, q)

    return EventSourceResponse(event_generator())


# ── Health ─────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8765"))
    uvicorn.run(app, host="0.0.0.0", port=port)
