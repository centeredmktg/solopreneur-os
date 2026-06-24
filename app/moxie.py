"""Moxie (withmoxie.com) Public API client.

Auth: X-API-KEY header. Base URL is per-workspace ("pod"), e.g.
https://pod01.withmoxie.com/api/public  (Workspace Settings -> Connected Apps ->
Integrations -> Enable Custom Integration). Rate limit: 100 requests / 5 min.

Endpoint paths verified live against a real workspace (2026-06-23) and
cross-checked with github.com/flyingwebie/withmoxie-mcp-server. All operations
sit under the `/action/` namespace:
  GET  /action/projects/search   list/search projects
  GET  /action/clients/list      list clients
  POST /action/tasks/create      create a task in a project (by project NAME)
  POST /action/timeWorked/create create a time entry (timerStart/End + userEmail)

We store nothing — Moxie is the system of record.
"""
from __future__ import annotations

import os

import httpx

BASE_URL = os.environ.get("MOXIE_BASE_URL", "").rstrip("/")
API_KEY = os.environ.get("MOXIE_API_KEY", "")
USER_EMAIL = os.environ.get("MOXIE_USER_EMAIL", "")  # owner of time entries


def configured() -> bool:
    return bool(BASE_URL and API_KEY)


def _get(path: str, params: dict | None = None):
    if not configured():
        raise RuntimeError("Moxie not configured: set MOXIE_BASE_URL and MOXIE_API_KEY.")
    r = httpx.get(f"{BASE_URL}{path}", headers={"X-API-KEY": API_KEY}, params=params, timeout=30.0)
    r.raise_for_status()
    return r.json()


def _post(path: str, body: dict) -> dict:
    if not configured():
        raise RuntimeError("Moxie not configured: set MOXIE_BASE_URL and MOXIE_API_KEY.")
    r = httpx.post(
        f"{BASE_URL}{path}",
        headers={"X-API-KEY": API_KEY, "Content-Type": "application/json"},
        json=body,
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json()


# ---- reads ----------------------------------------------------------------
def list_projects() -> list[dict]:
    """Live project list, trimmed to what the UI needs."""
    data = _get("/action/projects/search")
    return [
        {
            "id": p.get("id"),
            "name": p.get("name"),
            "clientId": p.get("clientId"),
            "active": p.get("active", True),
            "dueDate": p.get("dueDate"),
        }
        for p in (data or [])
    ]


def list_clients() -> list[dict]:
    data = _get("/action/clients/list")
    return [{"id": c.get("id"), "name": c.get("name")} for c in (data or [])]


# ---- writes ---------------------------------------------------------------
def create_task(
    name: str,
    project_name: str,
    client_name: str | None = None,
    due_date: str | None = None,
    status: str | None = None,
    priority: int | None = None,
    description: str | None = None,
) -> dict:
    """Create a task in a project. Tasks attach to a project by exact NAME."""
    body: dict = {"name": name, "projectName": project_name}
    if client_name:
        body["clientName"] = client_name
    if description:
        body["description"] = description
    if due_date:
        body["dueDate"] = due_date
    if status:
        body["status"] = status
    if priority is not None:
        body["priority"] = priority
    return _post("/action/tasks/create", body)


def create_time_entry(
    timer_start: str,
    timer_end: str,
    project_name: str | None = None,
    client_name: str | None = None,
    deliverable_name: str | None = None,
    notes: str | None = None,
    user_email: str | None = None,
) -> dict:
    """Create a time entry. Moxie tracks time as a start/end pair owned by a user."""
    email = user_email or USER_EMAIL
    if not email:
        raise RuntimeError("Set MOXIE_USER_EMAIL to record time entries.")
    body: dict = {"timerStart": timer_start, "timerEnd": timer_end, "userEmail": email}
    if project_name:
        body["projectName"] = project_name
    if client_name:
        body["clientName"] = client_name
    if deliverable_name:
        body["deliverableName"] = deliverable_name
    if notes:
        body["notes"] = notes
    return _post("/action/timeWorked/create", body)
