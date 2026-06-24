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
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import llm, moxie

APP_KEY = os.environ.get("APP_KEY", "")
# Per-instance brand (build-once, brand-per-deploy). Defaults to the product name.
BRAND = os.environ.get("APP_BRAND") or "Solopreneur OS"
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")


def _wordmark(brand: str) -> str:
    """Render the brand with its last word italicized, e.g. Sonya <em>OS</em>."""
    parts = brand.split()
    if len(parts) > 1:
        return " ".join(parts[:-1]) + f" <em>{parts[-1]}</em>"
    return f"<em>{brand}</em>"

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
    client_name: str | None = None


# Per-item push: each task carries its own client + project (assigned in-app
# from the live Moxie lists, so names match exactly).
class PushTask(BaseModel):
    title: str
    project_name: str | None = None
    client_name: str | None = None
    deadline: str | None = None


class TasksIn(BaseModel):
    tasks: list[PushTask]


class TimeNotesIn(BaseModel):
    notes: str


class TimeEntry(BaseModel):
    description: str
    minutes: int
    date: str | None = None
    client_name: str | None = None
    project_name: str | None = None


class TimeCommitIn(BaseModel):
    entries: list[TimeEntry]


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
    """Live project list (carries clientId so the UI can cascade client→project)."""
    _check_key(x_app_key)
    if not moxie.configured():
        raise HTTPException(status_code=501, detail="Moxie not connected.")
    projects = [p for p in moxie.list_projects() if p.get("active", True)]
    return {"projects": projects}


@app.get("/api/moxie/clients")
def moxie_clients(x_app_key: str | None = Header(default=None)) -> dict:
    """Live client list, for the per-item client picker."""
    _check_key(x_app_key)
    if not moxie.configured():
        raise HTTPException(status_code=501, detail="Moxie not connected.")
    return {"clients": moxie.list_clients()}


@app.post("/api/moxie/tasks")
def moxie_tasks(body: TasksIn, x_app_key: str | None = Header(default=None)) -> dict:
    """Push (HITL-reviewed) tasks into Moxie, each to its assigned project.

    Defer state to Moxie — we store nothing. Tasks without a project assigned are
    skipped and reported, so a partial assignment never silently drops work.
    """
    _check_key(x_app_key)
    if not body.tasks:
        raise HTTPException(status_code=400, detail="No tasks to push.")
    if not moxie.configured():
        raise HTTPException(
            status_code=501,
            detail="Moxie not connected yet. Add MOXIE_BASE_URL + MOXIE_API_KEY to enable pushing.",
        )
    results, skipped = [], []
    for t in body.tasks:
        if not t.project_name:
            skipped.append(t.title)
            continue
        res = moxie.create_task(
            name=t.title,
            project_name=t.project_name,
            client_name=t.client_name,
            due_date=t.deadline,
        )
        results.append({"task": t.title, "project": t.project_name, "moxie": res})
    return {"pushed": len(results), "skipped": skipped, "results": results}


@app.post("/api/report")
def report(body: ReportIn, x_app_key: str | None = Header(default=None)) -> dict:
    _check_key(x_app_key)
    if not body.notes.strip():
        raise HTTPException(status_code=400, detail="Paste your notes for the client first.")
    return {"report": llm.monthly_report(body.notes, body.client_name)}


@app.post("/api/moxie/time")
def moxie_time(body: TimeNotesIn, x_app_key: str | None = Header(default=None)) -> dict:
    """Preview: parse work notes into structured, per-entry billables."""
    _check_key(x_app_key)
    if not body.notes.strip():
        raise HTTPException(status_code=400, detail="Paste your work notes first.")
    entries = llm.parse_time_entries(body.notes)
    return {"entries": entries, "moxie_configured": moxie.configured()}


def _synth_timer(day: str | None, minutes: int) -> tuple[str, str]:
    """Moxie wants a start/end pair; synthesize from a date (@9am UTC) + minutes."""
    day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        start = datetime.fromisoformat(f"{day}T09:00:00+00:00")
    except ValueError:
        start = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
    end = start + timedelta(minutes=int(minutes))
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return start.strftime(fmt), end.strftime(fmt)


@app.post("/api/moxie/time/commit")
def moxie_time_commit(body: TimeCommitIn, x_app_key: str | None = Header(default=None)) -> dict:
    """Push per-item-assigned billables into Moxie."""
    _check_key(x_app_key)
    if not body.entries:
        raise HTTPException(status_code=400, detail="No entries to push.")
    if not moxie.configured():
        raise HTTPException(status_code=501, detail="Moxie not connected.")
    if not moxie.USER_EMAIL:
        raise HTTPException(
            status_code=501,
            detail="Set MOXIE_USER_EMAIL — Moxie records time entries against a user.",
        )
    results = []
    for e in body.entries:
        start, end = _synth_timer(e.date, e.minutes)
        res = moxie.create_time_entry(
            timer_start=start,
            timer_end=end,
            client_name=e.client_name,
            project_name=e.project_name,
            notes=e.description,
        )
        results.append({"entry": e.description, "project": e.project_name, "moxie": res})
    return {"pushed": len(results), "results": results}


# ---- static UI (mounted last so /api/* wins) ------------------------------
@app.get("/")
def index() -> HTMLResponse:
    with open(os.path.join(STATIC_DIR, "index.html")) as f:
        html = f.read()
    html = html.replace("{{BRAND}}", BRAND).replace("{{WORDMARK}}", _wordmark(BRAND))
    return HTMLResponse(html)


app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")
