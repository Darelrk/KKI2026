-- Read-only Pixhawk telemetry is sent as small Realtime Broadcast payloads.
-- The browser never receives a service-role key.

drop policy if exists "authenticated users can receive ASV telemetry" on realtime.messages;
create policy "authenticated users can receive ASV telemetry"
on realtime.messages
as permissive
for select
to authenticated
using (
  extension = 'broadcast'
  and (select realtime.topic()) like 'asv-telemetry:%'
);
