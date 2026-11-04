-- Staging-only manual migration. No approval rows or customer data in this file.
-- Reviewer provisions one approval with a fixed run, identity hash and three allowed slots.
-- Reservation is never released automatically, including on timeout/failed response.
create table public.eval_approvals (
  id text primary key,
  run_id text not null,
  identity_hash text not null,
  allowed_slots text[] not null check (cardinality(allowed_slots) between 1 and 3),
  budget numeric not null check (budget > 0),
  per_call numeric not null check (per_call > 0),
  reserved numeric not null default 0 check (reserved >= 0 and reserved <= budget),
  attempts integer not null default 0 check (attempts between 0 and 3),
  halted boolean not null default false
);
create table public.eval_attempts (
  approval_id text not null references public.eval_approvals(id),
  slot text not null,
  status text not null check (status in ('started','ok','error','unknown','over_limit')),
  reserved numeric not null,
  result jsonb,
  created_at timestamptz not null default now(),
  primary key (approval_id, slot)
);
alter table public.eval_approvals enable row level security;
alter table public.eval_attempts enable row level security;
revoke all on public.eval_approvals, public.eval_attempts from public, anon, authenticated;
grant select, insert, update on public.eval_approvals, public.eval_attempts to service_role;

create function public.eval_reserve(p_approval text, p_run text, p_slot text,
                                  p_identity text, p_amount numeric)
returns boolean language plpgsql security invoker set search_path = '' as $$
declare a public.eval_approvals%rowtype;
begin
  select * into a from public.eval_approvals where id = p_approval for update;
  if not found or a.halted or p_run is distinct from a.run_id
     or p_identity is distinct from a.identity_hash
     or p_slot is null or not (p_slot = any(a.allowed_slots))
     or p_amount is distinct from a.per_call
     or a.attempts >= 3 or a.reserved + a.per_call > a.budget then
    raise exception 'eval_reservation_denied';
  end if;
  -- Do not overlap calls; a crashed/in-flight reservation requires manual reconciliation.
  if exists (select 1 from public.eval_attempts where approval_id=p_approval
             and status in ('started','unknown','over_limit')) then
    raise exception 'eval_manual_recovery_required';
  end if;
  insert into public.eval_attempts(approval_id,slot,status,reserved)
    values(p_approval,p_slot,'started',a.per_call);
  update public.eval_approvals set attempts=attempts+1,reserved=reserved+a.per_call
    where id=p_approval;
  return true;
end $$;

create function public.eval_finish(p_approval text, p_run text, p_slot text, p_result jsonb)
returns boolean language plpgsql security invoker set search_path = '' as $$
declare a public.eval_approvals%rowtype;
declare s text;
begin
  select * into a from public.eval_approvals where id=p_approval for update;
  if not found or p_run is distinct from a.run_id then
    raise exception 'eval_finish_denied';
  end if;
  s := p_result->>'status';
  if s is null or s not in ('ok','error','unknown','over_limit') then
    raise exception 'eval_invalid_status';
  end if;
  update public.eval_attempts set status=s,result=p_result
    where approval_id=p_approval and slot=p_slot and status='started';
  if not found then raise exception 'eval_finish_denied'; end if;
  if s in ('unknown','over_limit') then
    update public.eval_approvals set halted=true where id=p_approval;
  end if;
  return true;
end $$;
revoke execute on function public.eval_reserve(text,text,text,text,numeric) from public,anon,authenticated;
revoke execute on function public.eval_finish(text,text,text,jsonb) from public,anon,authenticated;
grant execute on function public.eval_reserve(text,text,text,text,numeric) to service_role;
grant execute on function public.eval_finish(text,text,text,jsonb) to service_role;
