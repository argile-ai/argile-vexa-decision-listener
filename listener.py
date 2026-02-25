"""WebSocket listener that subscribes to Vexa transcript streams."""

import asyncio
import json
import logging
import os
from collections import defaultdict

import httpx
import websockets

from config import get_config
from llm import analyze_segments

logger = logging.getLogger("decision_listener.listener")

# Per-meeting state
_subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
_items_store: dict[str, list[dict]] = defaultdict(list)
_active_tasks: dict[str, asyncio.Task] = {}

VEXA_API_URL = os.getenv("VEXA_API_URL", "https://vexa.argile.ai")
VEXA_API_KEY = os.getenv("VEXA_API_KEY", "")

# Rolling window: last N segments to send to LLM
WINDOW_SIZE = 20
# Seconds between LLM analysis calls
ANALYSIS_INTERVAL = 10.0


def get_subscribers(meeting_id: str) -> list[asyncio.Queue]:
    return _subscribers[meeting_id]


def get_all_items(meeting_id: str) -> list[dict]:
    return _items_store.get(meeting_id, [])


def subscribe(meeting_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _subscribers[meeting_id].append(q)
    _ensure_listener(meeting_id)
    return q


def unsubscribe(meeting_id: str, q: asyncio.Queue) -> None:
    if meeting_id in _subscribers:
        try:
            _subscribers[meeting_id].remove(q)
        except ValueError:
            pass
        if not _subscribers[meeting_id]:
            del _subscribers[meeting_id]


def _ensure_listener(meeting_id: str) -> None:
    if meeting_id not in _active_tasks or _active_tasks[meeting_id].done():
        _active_tasks[meeting_id] = asyncio.create_task(
            _listen_and_analyze(meeting_id)
        )


async def _fetch_transcript_segments(meeting_id: str) -> list[dict]:
    """Fetch transcript segments from Vexa API via polling."""
    url = f"{VEXA_API_URL}/transcripts/google_meet/{meeting_id}"
    headers = {"X-API-Key": VEXA_API_KEY}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("segments", [])
    except Exception:
        logger.debug("Failed to fetch transcript for %s", meeting_id)
    return []


async def _try_websocket(meeting_id: str, segments_buffer: list[dict]) -> bool:
    """Try to connect to Vexa WebSocket for live segments. Returns False if unavailable."""
    ws_url = VEXA_API_URL.replace("https://", "wss://").replace("http://", "ws://")
    ws_url = f"{ws_url}/ws"

    try:
        async with websockets.connect(
            ws_url,
            additional_headers={"X-API-Key": VEXA_API_KEY},
            ping_interval=20,
            ping_timeout=10,
        ) as ws:
            # Subscribe to meeting transcripts
            await ws.send(json.dumps({
                "type": "subscribe",
                "meeting_id": meeting_id,
            }))

            async for msg in ws:
                try:
                    data = json.loads(msg)
                    if data.get("type") == "transcript_segment":
                        segments_buffer.append(data)
                        # Keep only last WINDOW_SIZE
                        if len(segments_buffer) > WINDOW_SIZE:
                            segments_buffer[:] = segments_buffer[-WINDOW_SIZE:]
                except json.JSONDecodeError:
                    continue
    except Exception:
        logger.debug("WebSocket not available for %s, using polling", meeting_id)
        return False
    return True


async def _listen_and_analyze(meeting_id: str) -> None:
    """Main loop: collect transcript segments and periodically analyze them."""
    logger.info("Starting listener for meeting %s", meeting_id)
    segments_buffer: list[dict] = []
    last_analyzed_count = 0

    # Try WebSocket in background, fall back to polling
    ws_task: asyncio.Task | None = None
    try:
        ws_task = asyncio.create_task(_try_websocket(meeting_id, segments_buffer))
    except Exception:
        pass

    try:
        while meeting_id in _subscribers and _subscribers[meeting_id]:
            # If WebSocket failed or isn't filling buffer, poll the API
            if not segments_buffer or (ws_task and ws_task.done()):
                polled = await _fetch_transcript_segments(meeting_id)
                if polled:
                    segments_buffer[:] = polled[-WINDOW_SIZE:]

            # Only analyze if we have new segments
            if len(segments_buffer) > last_analyzed_count:
                last_analyzed_count = len(segments_buffer)
                config = get_config()
                result = await asyncio.to_thread(
                    analyze_segments, segments_buffer[-WINDOW_SIZE:], config
                )

                if result and result.get("type") != "no_match":
                    result["meeting_id"] = meeting_id
                    _items_store[meeting_id].append(result)

                    # Broadcast to all SSE subscribers
                    for q in list(_subscribers.get(meeting_id, [])):
                        try:
                            q.put_nowait(result)
                        except asyncio.QueueFull:
                            pass

            await asyncio.sleep(ANALYSIS_INTERVAL)
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Listener error for meeting %s", meeting_id)
    finally:
        if ws_task and not ws_task.done():
            ws_task.cancel()
        _active_tasks.pop(meeting_id, None)
        logger.info("Stopped listener for meeting %s", meeting_id)
