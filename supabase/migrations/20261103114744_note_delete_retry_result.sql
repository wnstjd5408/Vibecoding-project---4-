-- MEG-79: Storage 호출 결과를 원자적으로 기록한다. FastAPI(service_role)만 호출한다.
-- attempts는 실패 횟수다. 기술 검토 4절의 초기 제안값 5회에서 자동 재시도를 멈춘다.
-- failed 작업은 SQL 점검 대상으로 남는다. 오류 원문·객체 경로를 오류 종류에 저장하지 않는다.
create function public.note_image_delete_result(
  p_job_ids bigint[],
  p_bucket text,
  p_error_kind text
)
returns void
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if p_error_kind is not null and p_error_kind not in ('storage_unavailable', 'storage_rejected') then
    raise exception 'unsupported storage error kind';
  end if;

  if p_error_kind is null then
    -- 앞서 pending을 읽은 동시 요청이 뒤늦게 성공한 경우에도 실제 삭제 성공이 우선한다.
    update public.storage_delete_jobs
       set status = 'done', done_at = now(), last_error_kind = null
     where id = any(p_job_ids) and bucket = p_bucket and status in ('pending', 'failed');
  else
    -- 행 잠금 안에서 누적한다. 다른 호출의 성공을 덮거나 실패 횟수를 유실하지 않는다.
    update public.storage_delete_jobs
       set attempts = case when attempts >= 4 then 5 else attempts + 1 end,
           last_error_kind = p_error_kind,
           status = case when attempts >= 4 then 'failed' else 'pending' end
     where id = any(p_job_ids) and bucket = p_bucket and status = 'pending';
  end if;
end;
$$;

revoke execute on function public.note_image_delete_result(bigint[], text, text) from public, anon, authenticated;
grant execute on function public.note_image_delete_result(bigint[], text, text) to service_role;
