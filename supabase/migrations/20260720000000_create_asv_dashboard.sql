-- ASV dashboard metadata and private fallback channel.
-- The Raspberry Pi uses the service-role key; the browser only receives data.

create table if not exists public.asv_live (
  id text primary key check (length(trim(id)) > 0),
  online boolean not null default false,
  model_status text not null default 'offline'
    check (model_status in ('offline', 'starting', 'running', 'error')),
  camera text not null default 'surface'
    check (camera in ('surface', 'underwater')),
  stream_url text
    check (stream_url is null or stream_url like 'https://%'),
  run_id text,
  updated_at timestamptz not null default timezone('utc', now())
);

comment on table public.asv_live is
  'Latest operational metadata for each autonomous surface vessel.';
comment on column public.asv_live.stream_url is
  'HTTPS camera bridge URL; continuous video never passes through Supabase.';

alter table public.asv_live enable row level security;

drop policy if exists "authenticated users can read ASV status" on public.asv_live;
create policy "authenticated users can read ASV status"
on public.asv_live
for select
to authenticated
using (true);

-- Private channels require an authenticated browser session. The client is
-- receive-only; service-role publishing bypasses this policy.
drop policy if exists "authenticated users can receive ASV fallback" on realtime.messages;
create policy "authenticated users can receive ASV fallback"
on realtime.messages
as permissive
for select
to authenticated
using (
  extension = 'broadcast'
  and (select realtime.topic()) like 'asv-camera:%'
);

create index if not exists asv_live_updated_at_idx
on public.asv_live (updated_at desc);
