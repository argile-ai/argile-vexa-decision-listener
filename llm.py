"""LLM integration for analyzing transcript segments."""

import json
import logging
import os

import anthropic

from config import TrackerConfig, build_system_prompt

logger = logging.getLogger("decision_listener.llm")

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def analyze_segments(
    segments: list[dict],
    config: TrackerConfig,
) -> dict | None:
    """Send transcript segments to the LLM and parse the response.

    Returns a dict with keys: type, summary, speaker, confidence.
    Returns None on error or empty input.
    """
    if not segments:
        return None

    transcript_text = "\n".join(
        f"[{s.get('speaker', 'Unknown')}] {s.get('text', '')}"
        for s in segments
        if s.get("text", "").strip()
    )

    if not transcript_text.strip():
        return None

    system_prompt = build_system_prompt(config)
    model = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001")

    try:
        response = _get_client().messages.create(
            model=model,
            max_tokens=256,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": f"Here are the latest transcript segments:\n\n{transcript_text}",
                }
            ],
        )

        text = response.content[0].text.strip()

        # Handle markdown code blocks
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        result = json.loads(text)
        return {
            "type": result.get("type", "no_match"),
            "summary": result.get("summary", ""),
            "speaker": result.get("speaker"),
            "confidence": result.get("confidence", 0.0),
        }

    except json.JSONDecodeError:
        logger.warning("LLM returned invalid JSON: %s", text[:200])
        return None
    except Exception:
        logger.exception("LLM call failed")
        return None
