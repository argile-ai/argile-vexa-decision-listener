# Vexa Decision Listener

Real-time meeting intelligence service for [Vexa](https://github.com/Vexa-ai/vexa). Subscribes to live meeting transcripts and uses an LLM to detect **decisions**, **action items**, and **architecture statements**.

Built to work with the [Vexa Dashboard](https://github.com/Vexa-ai/Vexa-Dashboard) tracker feature.

## Quick Start

```bash
cp .env.example .env
# Edit .env with your API keys

# Docker
docker compose up -d

# Or locally
pip install -r requirements.txt
python main.py
```

The service runs on port **8765** by default.

## API

All endpoints except `/health` require a Bearer token via the `Authorization` header:

```
Authorization: Bearer <API_KEY>
```

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/config` | Yes | Get tracker configuration |
| `PUT` | `/config` | Yes | Update tracker configuration |
| `POST` | `/config/reset` | Yes | Reset to default config |
| `GET` | `/decisions/{meeting_id}` | Yes | SSE stream of real-time decisions |
| `GET` | `/decisions/{meeting_id}/all` | Yes | Get all captured items for a meeting |
| `GET` | `/health` | No | Health check |

## How It Works

1. When an SSE client subscribes to `/decisions/{meeting_id}`, the listener starts polling the Vexa API for transcript segments (or connects via WebSocket if available)
2. Every ~10 seconds, a rolling window of the latest segments is sent to Claude (Haiku by default) with the tracker prompt
3. If a decision, action item, or architecture statement is detected, it's broadcast to all SSE subscribers
4. The Dashboard displays these in real-time with approve/discard controls

## Configuration

Set via environment variables or `.env`:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `VEXA_API_URL` | Yes | - | Vexa API base URL |
| `VEXA_API_KEY` | Yes | - | Vexa user API key |
| `ANTHROPIC_API_KEY` | Yes | - | Anthropic API key for Claude |
| `LLM_MODEL` | No | `claude-haiku-4-5-20251001` | Model to use |
| `API_KEY` | Yes | - | Bearer token for API authentication |
| `PORT` | No | `8765` | Listener port |

## License

Apache-2.0
