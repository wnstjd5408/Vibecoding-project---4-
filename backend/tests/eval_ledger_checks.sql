-- Run only in a disposable Postgres database, after shared_ledger.sql.
insert into public.eval_approvals(id,run_id,identity_hash,allowed_slots,budget,per_call)
values ('fixture','run','hash',array['C0','C1','C2'],0.9,0.2);
set role service_role;
select public.eval_reserve('fixture','run','C0','hash',0.2);
do $$ begin
  begin
    perform public.eval_reserve('fixture','run','C1','hash',0.2);
    raise exception 'TEST in-flight reserve permitted';
  exception when others then
    if sqlerrm <> 'eval_manual_recovery_required' then raise; end if;
  end;
end $$;
select public.eval_finish('fixture','run','C0','{"status":"ok"}');
do $$ begin
  begin
    perform public.eval_reserve('fixture','run','C0','hash',0.2);
    raise exception 'TEST duplicate permitted';
  exception when unique_violation then null;
  end;
  begin
    perform public.eval_reserve('fixture','run','C1','wrong',0.2);
    raise exception 'TEST changed identity permitted';
  exception when others then
    if sqlerrm <> 'eval_reservation_denied' then raise; end if;
  end;
end $$;
select public.eval_reserve('fixture','run','C1','hash',0.2);
select public.eval_finish('fixture','run','C1','{"status":"unknown"}');
do $$ begin
  begin
    perform public.eval_reserve('fixture','run','C2','hash',0.2);
    raise exception 'TEST unknown permitted';
  exception when others then
    if sqlerrm <> 'eval_reservation_denied' then raise; end if;
  end;
  if (select reserved from public.eval_approvals where id='fixture') <> 0.4 then
    raise exception 'TEST reservation lost';
  end if;
end $$;
reset role;
set role anon;
do $$ begin
  begin
    perform public.eval_reserve('fixture','run','C2','hash',0.2);
    raise exception 'TEST anon allowed';
  exception when insufficient_privilege then null;
  end;
end $$;
reset role;
