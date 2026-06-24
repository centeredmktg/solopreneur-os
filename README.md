# Solopreneur OS

A small, branded toolkit for solo virtual assistants / fractional-ops partners.
Three tools, one deployable app:

1. **Priority Engine** — paste a client's word-vomit (Slack / email / text), get
   back a prioritized, client-ready plan (Now / Next / Later).
2. **Monthly Report** — paste rough notes, get a warm, one-page client update.
3. **Task → Time (Moxie)** — paste work notes, get structured time entries,
   optionally pushed straight into [Moxie](https://withmoxie.com) for billing.

Design partner / first user: **Sonya Jay Solutions**. Built to generalize to any
solo VA on Moxie.

## Stack

- **FastAPI** serving a static single-page UI + JSON endpoints
- **Claude** (`claude-sonnet-4-6` by default) for the three tools, with prompt
  caching on the system prompts
- **Moxie Public API** for the Task → Time push
- Deploys on **Railway** via the included `Dockerfile`

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY (and APP_KEY)
uvicorn app.main:app --reload
# open http://localhost:8000
```

## Deploy (Railway)

1. Connect this repo. Railway uses the `Dockerfile`.
2. Set env vars (see `.env.example`):
   - `ANTHROPIC_API_KEY` — **required**
   - `APP_KEY` — **strongly recommended** (gates `/api/*` so the public URL
     can't be used to run up the Anthropic bill)
   - `MOXIE_BASE_URL` + `MOXIE_API_KEY` — optional, enables the Task → Time push
   - `CLAUDE_MODEL` — optional, e.g. `claude-opus-4-8` for max quality
3. Healthcheck is `/api/health`.

## Endpoints

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/health` | — | status, model, moxie/key config |
| POST | `/api/priority` | `{dump, client_name?}` | `{tasks, questions}` (structured, editable) |
| GET | `/api/moxie/projects` | — | `{projects}` — live project list from Moxie |
| POST | `/api/moxie/tasks` | `{tasks, project_name, client_name?}` | `{pushed, results}` — pushes HITL-reviewed tasks into the chosen Moxie project |
| POST | `/api/report` | `{notes}` | `{report}` (markdown) |
| POST | `/api/moxie/time` | `{notes, commit?}` | parsed `{entries}`, or `{results}` if committed |

## Design principle: defer state to the backend

The app stores **nothing**. Moxie is the system of record for tasks, projects,
and time. The Priority Engine extracts a structured task set you review and edit
(HITL), then **pushes into Moxie** — it does not persist a parallel task store.
This is the wedge: a nicer AI front door over tools the user already owns. Future
backends (HubSpot, GoHighLevel, Asana) slot in as new adapter modules + routes.

All `/api/*` calls require the `X-App-Key` header when `APP_KEY` is set.

## Moxie note

The exact Create Time Entry path + field names render on each workspace's own
"Public API Endpoints & JSON Payloads" page once the custom integration is
enabled. Confirm against the live docs (or the community MCP server at
`github.com/flyingwebie/withmoxie-mcp-server`) and set `MOXIE_TIME_ENTRY_PATH`
if it differs from the default. See `app/moxie.py`.
