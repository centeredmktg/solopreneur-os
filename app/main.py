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

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import llm, moxie

APP_KEY = os.environ.get("APP_KEY", "")
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")

app = FastAPI(title="Solopreneur OS")


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
    return {"plan": llm.priority_plan(body.dump, body.client_name)}


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

    # Preview-only by default. Pushing to Moxie is opt-in via commit=true and
    # requires the Moxie integration to be configured.
    if body.commit:
        if not moxie.configured():
            raise HTTPException(
                status_code=501,
                detail="Moxie not connected yet. Add MOXIE_BASE_URL + MOXIE_API_KEY to enable pushing.",
            )
        results = []
        for e in entries:
            res = moxie.create_time_entry(
                e["description"], int(e["minutes"]), e.get("client"), e.get("date")
            )
            results.append({"entry": e, "moxie": res})
        return {"committed": True, "results": results}

    return {"committed": False, "entries": entries, "moxie_configured": moxie.configured()}


# ---- static UI (mounted last so /api/* wins) ------------------------------
@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")
