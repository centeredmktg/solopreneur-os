"""Anthropic Claude calls for the Solopreneur OS tools.

Model choice: claude-sonnet-4-6 — the quality/cost balance for customer-facing,
higher-volume generation. Swap to claude-opus-4-8 for max quality (see MODEL).

Prompt caching: the system prompts (prompts.py) are large and byte-stable, so we
mark them cache_control: ephemeral. Repeated calls within the 5-min TTL bill the
cached prefix at ~0.1x. Verify via response.usage.cache_read_input_tokens.
"""
from __future__ import annotations

import os
import json

import anthropic

from . import prompts

# `or` (not a default arg) so an empty CLAUDE_MODEL= in .env falls back too.
MODEL = os.environ.get("CLAUDE_MODEL") or "claude-sonnet-4-6"

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        # Reads ANTHROPIC_API_KEY from the environment.
        _client = anthropic.Anthropic()
    return _client


def _generate(system_prompt: str, user_text: str, max_tokens: int = 4000) -> str:
    """Single-shot text generation with a cached system prefix."""
    resp = _get_client().messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_text}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()


_PRIORITY_SCHEMA = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "area": {
                        "type": "string",
                        "enum": ["Administrative", "Business Operations", "Creative + Design"],
                    },
                    "priority": {"type": "string", "enum": ["now", "next", "later"]},
                    "deadline": {"type": ["string", "null"]},
                    "needs_from_client": {"type": ["string", "null"]},
                },
                "required": ["title", "area", "priority", "deadline", "needs_from_client"],
                "additionalProperties": False,
            },
        },
        "questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["tasks", "questions"],
    "additionalProperties": False,
}


def parse_priority(dump: str, client_name: str | None = None) -> dict:
    """Extract a structured, editable task set from a client's word-vomit."""
    user = dump if not client_name else f"Client: {client_name}\n\n{dump}"
    resp = _get_client().messages.create(
        model=MODEL,
        max_tokens=3000,
        system=[
            {
                "type": "text",
                "text": prompts.PRIORITY_ENGINE,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": _PRIORITY_SCHEMA}},
    )
    text = next((b.text for b in resp.content if b.type == "text"), "{}")
    return json.loads(text)


def monthly_report(notes: str) -> str:
    return _generate(prompts.MONTHLY_REPORT, notes, max_tokens=4000)


# Structured-output schema for the task->time parser. additionalProperties:false
# and required on every object is required by the structured-outputs feature.
_TIME_ENTRIES_SCHEMA = {
    "type": "object",
    "properties": {
        "entries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "minutes": {"type": "integer"},
                    "client": {"type": ["string", "null"]},
                    "date": {"type": ["string", "null"]},
                },
                "required": ["description", "minutes", "client", "date"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["entries"],
    "additionalProperties": False,
}


def parse_time_entries(notes: str) -> list[dict]:
    """Parse freeform work notes into structured time entries."""
    resp = _get_client().messages.create(
        model=MODEL,
        max_tokens=2000,
        system=[
            {
                "type": "text",
                "text": prompts.TASK_TO_TIME,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": notes}],
        output_config={"format": {"type": "json_schema", "schema": _TIME_ENTRIES_SCHEMA}},
    )
    text = next((b.text for b in resp.content if b.type == "text"), "{}")
    return json.loads(text).get("entries", [])
