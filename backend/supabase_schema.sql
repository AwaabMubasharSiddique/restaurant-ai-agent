-- The Olive Branch — Supabase schema
-- Safe to run on a FRESH project or an EXISTING one (idempotent):
--   create table if not exists  +  alter table ... add column if not exists.
-- The backend uses the service_role key, so this works with or without RLS.

-- ── Reservations ──────────────────────────────────────────────
create table if not exists reservations (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  date        date not null,
  time        text not null,                 -- "HH:MM" slot start
  party_size  int  not null,
  phone       text not null,
  table_id    text,                          -- assigned table, e.g. "T3" (null = staff-seated)
  status      text not null default 'pending',
  created_at  timestamptz not null default now()
);

-- Adds the table assignment column to an older reservations table (no-op on a
-- fresh one):
alter table reservations add column if not exists table_id text;

-- ── Orders ────────────────────────────────────────────────────
create table if not exists orders (
  id             uuid primary key default gen_random_uuid(),
  items          jsonb not null,              -- [{name, quantity, price}, ...]
  customer_name  text,
  phone          text,
  address        text,                        -- delivery address
  total          numeric,
  notes          text,
  status         text not null default 'pending',
  created_at     timestamptz not null default now()
);

-- Migration for an orders table created before contact/total existed.
-- (No-ops if you ran the create above on a fresh project.)
alter table orders add column if not exists customer_name text;
alter table orders add column if not exists phone         text;
alter table orders add column if not exists address       text;
alter table orders add column if not exists total         numeric;

-- ── Conversation logs ─────────────────────────────────────────
create table if not exists conversation_logs (
  id               uuid primary key default gen_random_uuid(),
  conversation_id  text not null,             -- == session id
  timestamp        timestamptz not null default now(),
  customer_message text,
  detected_intent  text,
  agent_response   text,
  needs_human      boolean not null default false,
  created_at       timestamptz not null default now()
);

-- ── Newest-first read performance (optional, cheap) ───────────
create index if not exists idx_reservations_created_at on reservations (created_at desc);
create index if not exists idx_orders_created_at        on orders (created_at desc);
create index if not exists idx_logs_created_at          on conversation_logs (created_at desc);

-- Staff read newest-first, e.g.:
--   select * from orders order by created_at desc;
