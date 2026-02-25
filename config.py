"""Tracker configuration with persistence."""

import json
import logging
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger("decision_listener.config")

CONFIG_PATH = Path("tracker_config.json")

DEFAULT_CONFIG = {
    "name": "Meeting Intelligence",
    "description": "Captures key decisions, action items, and architecture statements from live meetings.",
    "categories": [
        {
            "key": "decision",
            "label": "Decision",
            "description": "A clear agreement or choice made by the group (e.g. 'We decided to use PostgreSQL').",
            "enabled": True,
        },
        {
            "key": "action_item",
            "label": "Action Item",
            "description": "A task assigned to someone with an implicit or explicit deadline (e.g. 'John will send the report by Friday').",
            "enabled": True,
        },
        {
            "key": "architecture_statement",
            "label": "Architecture",
            "description": "A technical design choice or system constraint (e.g. 'We will migrate to microservices').",
            "enabled": True,
        },
    ],
    "extra_instructions": "",
}


class TrackerCategory(BaseModel):
    key: str
    label: str
    description: str
    enabled: bool = True


class TrackerConfig(BaseModel):
    name: str
    description: str
    categories: list[TrackerCategory]
    extra_instructions: str = ""


_current: TrackerConfig | None = None


def _load_from_disk() -> TrackerConfig:
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text())
            return TrackerConfig(**data)
        except Exception:
            logger.warning("Corrupt config file, using defaults")
    return TrackerConfig(**DEFAULT_CONFIG)


def get_config() -> TrackerConfig:
    global _current
    if _current is None:
        _current = _load_from_disk()
    return _current


def save_config(cfg: TrackerConfig) -> TrackerConfig:
    global _current
    _current = cfg
    CONFIG_PATH.write_text(cfg.model_dump_json(indent=2))
    return _current


def reset_config() -> TrackerConfig:
    global _current
    _current = TrackerConfig(**DEFAULT_CONFIG)
    CONFIG_PATH.write_text(_current.model_dump_json(indent=2))
    return _current


def build_system_prompt(cfg: TrackerConfig) -> str:
    enabled = [c for c in cfg.categories if c.enabled]
    if not enabled:
        return "No categories enabled. Return no_match for everything."

    categories_block = "\n".join(
        f'- **{c.key}**: {c.description}' for c in enabled
    )
    categories_block += '\n- **no_match**: nothing significant to capture right now'

    extra = ""
    if cfg.extra_instructions.strip():
        lines = cfg.extra_instructions.strip().split("\n")
        extra = "\nAdditional rules:\n" + "\n".join(f"- {l.strip()}" for l in lines if l.strip())

    return f"""You are a precise meeting analyst.
You are given a rolling window of recent transcript segments from a live meeting.

Your job: detect exactly ONE of the following, if present:
{categories_block}
{extra}

Respond with a JSON object:
{{"type": "<category_key or no_match>", "summary": "<one-sentence summary>", "speaker": "<speaker name if clear, else null>", "confidence": <0.0 to 1.0>}}

Rules:
- Be conservative. Only capture explicit, clear statements.
- Do NOT hallucinate or infer decisions that were not clearly stated.
- If unsure, return {{"type": "no_match", "summary": "", "speaker": null, "confidence": 0.0}}
- Always respond with valid JSON only, no extra text."""
