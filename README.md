# The Olive Branch — Restaurant Customer-Service AI

A FastAPI + LangGraph agent that answers a restaurant's customers: menu & FAQ
questions (via RAG), hours/location, complaints, takeout orders, and
availability-aware **reservation requests** — plus a polished React chat UI.

> **Reservations are never auto-confirmed.** The agent checks slot availability,
> saves a request as `pending`, and tells the customer the restaurant will
> confirm shortly. A human is always the final approver.

---

## Architecture at a glance

```
                         ┌──────────────────────────────┐
  React + Vite UI  ──►   │  FastAPI  /chat               │
  (frontend/)            │  CORS · slowapi · session id  │
                         └───────────────┬───────────────┘
                                         │ run_agent(message, session_id)
                                         ▼
                         ┌──────────────────────────────┐
                         │  LangGraph agent (agent/)     │
                         │  classify → route → handler   │
                         │  → log → END                  │
                         └───┬───────────┬──────────┬────┘
                             │           │          │
                   ┌─────────▼──┐  ┌─────▼─────┐  ┌─▼──────────────┐
                   │ rag/       │  │ tools/    │  │ memory          │
                   │ FAISS menu │  │ reserve / │  │ (checkpointer,  │
                   │ + FAQ      │  │ order /   │  │  per session)   │
                   └────────────┘  │ avail /   │  └────────────────┘
                                   │ logging   │
                                   └─────┬─────┘
                                         ▼
                                 Supabase tables
                            (reservations, orders, logs)
                       — or an in-memory fallback if unset —
```

**Why the three modules are separate**

- **`agent/`** decides *what to do* (intent → route → respond). It owns
  conversation logic and nothing else.
- **`rag/`** owns *what the restaurant knows* (menu, hours, policies). Update a
  text file and re-embed; no agent code changes.
- **`tools/`** owns *side effects on the world* (save reservation, count a slot,
  log a turn). They're plain functions the agent calls — independently testable
  and swappable (in-memory ↔ Supabase) without touching the graph.

This is the classic split: **reasoning** (agent) vs **knowledge** (rag) vs
**actions** (tools). Each can be tested and changed in isolation.

---

## Project layout

```
Restaurant/
├── backend/                FastAPI + LangGraph service (deploy this to Railway)
│   ├── main.py             FastAPI app: /chat, /health, CORS, rate limit
│   ├── config.py           Env-driven settings (pydantic-settings)
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── pytest.ini
│   ├── Dockerfile          Multi-stage build
│   ├── .env.example
│   ├── data/
│   │   └── restaurant_info.txt   Menu + hours + policies (RAG source)
│   ├── models/
│   │   └── schemas.py      Reservation, Order, ConversationLog, DTOs
│   ├── rag/
│   │   ├── ingest.py       load → chunk → embed (text-embedding-3-small) → FAISS
│   │   └── retriever.py    load index + similarity search
│   ├── tools/
│   │   ├── store.py        Supabase OR in-memory persistence
│   │   ├── reservation.py  save_reservation
│   │   ├── order.py        save_order
│   │   ├── availability.py per-slot counting, nearby open slots
│   │   └── logging_tool.py log_conversation
│   ├── agent/
│   │   ├── state.py        AgentState (TypedDict + add_messages)
│   │   ├── memory.py       LangGraph checkpointer (per-session memory)
│   │   ├── llm.py          ChatOpenAI factory
│   │   ├── prompts.py      system prompts
│   │   ├── nodes.py        classifier, router, handlers, logger
│   │   └── graph.py        StateGraph wiring + run_agent()
│   └── tests/              Offline pytest suite
└── frontend/               React + Vite chat UI
```

> All Python imports are rooted at `backend/`, so run backend commands from
> inside `backend/` (or set Railway's **Root Directory** to `backend`).

---

## Setup (backend)

```bash
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # then fill in OPENAI_API_KEY (Supabase optional)
```

Build the RAG index from the menu file (optional — it auto-builds on first use):

```bash
python -m rag.ingest
```

Run the API:

```bash
uvicorn main:app --reload
# http://localhost:8000/docs
```

Quick test:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Do you have vegan options?"}'
```

## Setup (frontend)

```bash
cd frontend
npm install
cp .env.example .env         # VITE_API_URL=http://localhost:8000
npm run dev                  # http://localhost:5173
```

## Tests

The suite is **offline** — it covers the pure logic (slot-counting, the
persistence fallback, schema validation) with no OpenAI key or Supabase.

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

## Docker (backend)

```bash
cd backend
docker build -t olive-branch-ai .
docker run -p 8000:8000 --env-file .env olive-branch-ai
```

---

## Supabase

The app runs with **no database** (in-memory fallback) if `SUPABASE_URL` /
`SUPABASE_KEY` are unset. To persist, create these tables. The restaurant reads
them directly (no notifications in v1), so each has a `created_at` for
**newest-first** sorting and a `status` defaulting to `pending`.

```sql
create table reservations (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  date        date not null,
  time        text not null,          -- "HH:MM" slot start
  party_size  int  not null,
  phone       text not null,
  table_id    text,                   -- assigned table, e.g. "T3" (null = staff-seated)
  status      text not null default 'pending',
  created_at  timestamptz not null default now()
);

create table orders (
  id             uuid primary key default gen_random_uuid(),
  items          jsonb not null,        -- [{name, quantity, price}, ...]
  customer_name  text,
  phone          text,
  address        text,                  -- delivery address
  total          numeric,
  notes          text,
  status         text not null default 'pending',
  created_at     timestamptz not null default now()
);
-- Already have an older orders table? Add the new columns:
--   alter table orders
--     add column customer_name text,
--     add column phone text,
--     add column address text,
--     add column total numeric;

create table conversation_logs (
  id              uuid primary key default gen_random_uuid(),
  conversation_id text not null,      -- == session id
  timestamp       timestamptz not null default now(),
  customer_message text,
  detected_intent text,
  agent_response  text,
  needs_human     boolean not null default false,
  created_at      timestamptz not null default now()
);

-- Newest-first is how staff watch these:
--   select * from reservations order by created_at desc;
```

Use the **service_role** key on the server (inserts bypass RLS). Never ship it
to the browser.

---

## How it works

**Intent → routing.** `classify_intent` asks the model for one of six intents
plus a confidence. A conditional edge (`route_intent`) sends the turn to exactly
one handler. Below `LOW_CONFIDENCE_THRESHOLD`, or for `other`, it routes to a
polite human hand-off (`needs_human = true`).

**Handlers.**
- `menu_question` / `hours_location` — RAG retrieve → grounded answer.
- `complaint` — empathetic reply, `needs_human = true`.
- `order` — extract items, save `pending`.
- `reservation` — gather details across turns, then guard the request: reject
  past dates and times outside opening hours, hand parties too big for the
  largest table to staff (`needs_human`), otherwise assign a free table that
  fits and save `pending`, or offer the nearest open slots.
- `other` / low-confidence — hand off to a human.

**Memory.** The compiled graph uses a checkpointer keyed by `thread_id =
session_id`. Prior messages load before each run and the reply is appended
after, so multi-turn reservations ("a table for two" … "Friday 7pm" … "John,
555-…") accumulate naturally. Swap `MemorySaver` for `SqliteSaver`/Postgres in
`agent/memory.py` for durability — no node changes.

**Availability (table-level booking).** The dining room is a fixed set of
tables (`RESTAURANT_TABLES` in `config.py`, e.g. `T1`/`T2` = 4 seats, `T3` = 8).
For a requested date+time we assign the **smallest free table that fits the
party** (tightest-fit, so the big table stays open for big groups) and hold it
for `SEATING_DURATION_MINUTES`. Two parties can therefore never be given the
same table at overlapping times, and a 7:00 booking still blocks part of 8:00 on
that table. No free table → suggest the closest open slots. A party larger than
the biggest table can't sit at one table, so it's handed to staff (joining
tables is a human call). Rescheduling re-runs the assignment, excluding the
booking's own row so it doesn't clash with itself.

### What's modeled vs. what's next

Modeled: per-table assignment, seat-count fit, seating duration. Not yet:
indoor/outdoor or joinable tables, variable seating durations by party size, and
table merging for large groups. Because availability is isolated behind
`find_table()` / `is_available()` / `nearby_open_slots()`, adding those doesn't
touch the agent or graph.

### Why a human stays the final approver

The agent says "received / pending", never "confirmed/booked". Real seating
depends on no-shows, walk-ins, merged tables, and judgment the model can't see.
Saving as `pending` keeps the agent helpful and fast while a person makes the
binding call — low risk, easy to audit via `conversation_logs`.

---

## Notes & limitations (v1)

- In-memory store and `MemorySaver` are **per-process** — fine for a demo, not
  for horizontal scaling. Move to Supabase + a durable checkpointer for prod.
- Rate limiting is per-IP via slowapi (`RATE_LIMIT`, default `20/minute`).
- All secrets come from the environment; nothing is hard-coded.
