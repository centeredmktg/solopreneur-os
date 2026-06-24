"""Solopreneur OS — FastAPI app.

Serves a branded single-page UI and three tool endpoints:
  POST /api/priority    word-vomit -> prioritized plan          (Claude)
  POST /api/report      rough notes -> client-ready monthly recap (Claude)
  POST /api/moxie/time  work notes -> parsed time entries -> Moxie (Claude + Moxie API)

Access gate: if APP_KEY is set, every /api/* call must send a matching
X-App-Key header. This stops a public URL from being used to run up the
Anthropic bill. Leave APP_KEY unset only for local dev.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()  # local dev: read .env. No-op on Railway (real env vars set).

import anthropic
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import llm, moxie

APP_KEY = os.environ.get("APP_KEY", "")
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")

app = FastAPI(title="Solopreneur OS")


@app.exception_handler(anthropic.APIStatusError)
async def _anthropic_error(request: Request, exc: anthropic.APIStatusError) -> JSONResponse:
    # Surface a clean message instead of a raw 500 (e.g. low balance, rate limit).
    msg = getattr(exc, "message", str(exc))
    return JSONResponse(status_code=502, content={"detail": f"AI service error: {msg}"})


def _check_key(x_app_key: str | None) -> None:
    if APP_KEY and x_app_key != APP_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing app key.")


# ---- request models -------------------------------------------------------
class PriorityIn(BaseModel):
    dump: str
    client_name: str | None = None


class ReportIn(BaseModel):
    notes: str


class TimeIn(BaseModel):
    notes: str
    commit: bool = False  # if true, push parsed entries to Moxie


class TaskItem(BaseModel):
    title: str
    area: str | None = None
    priority: str | None = None
    deadline: str | None = None
    needs_from_client: str | None = None


class TasksIn(BaseModel):
    tasks: list[TaskItem]
    project_name: str  # Moxie attaches tasks to a project by exact name
    client_name: str | None = None


# ---- API ------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "model": llm.MODEL,
        "moxie_configured": moxie.configured(),
        "key_required": bool(APP_KEY),
    }


@app.post("/api/priority")
def priority(body: PriorityIn, x_app_key: str | None = Header(default=None)) -> dict:
    _check_key(x_app_key)
    if not body.dump.strip():
        raise HTTPException(status_code=400, detail="Paste the client's messages first.")
    result = llm.parse_priority(body.dump, body.client_name)
    result["moxie_configured"] = moxie.configured()
    return result


@app.get("/api/moxie/projects")
def moxie_projects(x_app_key: str | None = Header(default=None)) -> dict:
    """Live project list from Moxie, for the task-push picker."""
    _check_key(x_app_key)
    if not moxie.configured():
        raise HTTPException(status_code=501, detail="Moxie not connected.")
    projects = [p for p in moxie.list_projects() if p.get("active", True)]
    return {"projects": projects}


@app.post("/api/moxie/tasks")
def moxie_tasks(body: TasksIn, x_app_key: str | None = Header(default=None)) -> dict:
    """Push (HITL-reviewed) tasks into Moxie. Defer state to Moxie — we store nothing."""
    _check_key(x_app_key)
    if not body.tasks:
        raise HTTPException(status_code=400, detail="No tasks to push.")
    if not body.project_name:
        raise HTTPException(status_code=400, detail="Pick a project to add these tasks to.")
    if not moxie.configured():
        raise HTTPException(
            status_code=501,
            detail="Moxie not connected yet. Add MOXIE_BASE_URL + MOXIE_API_KEY to enable pushing.",
        )
    results = []
    for t in body.tasks:
        res = moxie.create_task(
            name=t.title,
            project_name=body.project_name,
            client_name=body.client_name,
            due_date=t.deadline,
        )
        results.append({"task": t.title, "moxie": res})
    return {"pushed": len(results), "results": results}


@app.post("/api/report")
def report(body: ReportIn, x_app_key: str | None = Header(default=None)) -> dict:
    _check_key(x_app_key)
    if not body.notes.strip():
        raise HTTPException(status_code=400, detail="Paste your notes for the client first.")
    return {"report": llm.monthly_report(body.notes)}


@app.post("/api/moxie/time")
def moxie_time(body: TimeIn, x_app_key: str | None = Header(default=None)) -> dict:
    _check_key(x_app_key)
    if not body.notes.strip():
        raise HTTPException(status_code=400, detail="Paste your work notes first.")

    entries = llm.parse_time_entries(body.notes)

    # Preview-only by default. Pushing to Moxie is opt-in via commit=true.
    if body.commit:
        if not moxie.configured():
            raise HTTPException(
                status_code=501,
                detail="Moxie not connected yet. Add MOXIE_BASE_URL + MOXIE_API_KEY to enable pushing.",
            )
        if not moxie.USER_EMAIL:
            raise HTTPException(
                status_code=501,
                detail="Set MOXIE_USER_EMAIL — Moxie records time entries against a user.",
            )
        results = []
        for e in entries:
            # Moxie wants a timer start/end pair. We have minutes + an optional
            # date, so synthesize a start (date @ 9am UTC) and end (+minutes).
            day = e.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
            try:
                start = datetime.fromisoformat(f"{day}T09:00:00+00:00")
            except ValueError:
                start = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
            end = start + timedelta(minutes=int(e["minutes"]))
            res = moxie.create_time_entry(
                timer_start=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                timer_end=end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                client_name=e.get("client"),
                notes=e["description"],
            )
            results.append({"entry": e, "moxie": res})
        return {"committed": True, "results": results}

    return {"committed": False, "entries": entries, "moxie_configured": moxie.configured()}


# ---- static UI (mounted last so /api/* wins) ------------------------------
@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")
