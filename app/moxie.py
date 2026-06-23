"""Moxie (withmoxie.com) Public API client — Task -> Time billing.

Auth: X-API-KEY header. Base URL is per-workspace ("pod"), e.g.
https://pod00.withmoxie.dev  (the value Moxie shows under
Workspace Settings -> Connected Apps -> Integrations -> Enable Custom Integration).
Rate limit: 100 requests / 5 min.

NOTE: the exact Create Time Entry path + field names render on the workspace's
own "Public API Endpoints & JSON Payloads" page once the integration is enabled.
Confirm against the live docs (or the community MCP server,
github.com/flyingwebie/withmoxie-mcp-server) before relying on this in prod.
The endpoint path is configurable via MOXIE_TIME_ENTRY_PATH so we can correct it
without a code change.
"""
from __future__ import annotations

import os

import httpx

BASE_URL = os.environ.get("MOXIE_BASE_URL", "").rstrip("/")
API_KEY = os.environ.get("MOXIE_API_KEY", "")
# Default to the documented public-API namespace; override once verified.
TIME_ENTRY_PATH = os.environ.get("MOXIE_TIME_ENTRY_PATH", "/api/public/timeentries/create")


def configured() -> bool:
    return bool(BASE_URL and API_KEY)


def create_time_entry(description: str, minutes: int, client: str | None, date: str | None) -> dict:
    """Create a single time entry in Moxie. Returns the API response JSON."""
    if not configured():
        raise RuntimeError("Moxie not configured: set MOXIE_BASE_URL and MOXIE_API_KEY.")

    payload: dict = {"description": description, "minutes": minutes}
    if client:
        payload["client"] = client
    if date:
        payload["date"] = date

    resp = httpx.post(
        f"{BASE_URL}{TIME_ENTRY_PATH}",
        headers={"X-API-KEY": API_KEY, "Content-Type": "application/json"},
        json=payload,
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()
