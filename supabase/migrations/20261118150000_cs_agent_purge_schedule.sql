-- CS Agent 대화 7일 보관 정리를 하루 한 번 예약한다 (MEG-235, 기술 검토 v0.4 2절 Q3·5.3절)
-- 정리 함수 agent_purge_expired는 T1(MEG-232) 마이그레이션에 있다. 이 파일은 예약만 만든다.
--
-- 예약 엔진은 Supabase Cron(pg_cron)이다. 활성화 SQL은 Supabase 문서를 따른다:
--   https://supabase.com/docs/guides/cron/install
-- pg_cron을 설치할 수 없는 DB(저장소 SQL 시험이 쓰는 일반 PostgreSQL 17 등)에서는 예약을 만들지 않고 건너뛴다.
-- Supabase 프로젝트에는 pg_cron이 있으므로(prd 확장 목록 조회, 2026-11-18) 이 분기는 원격에서 타지 않는다.
--
-- 시각: 매일 18:00 GMT = 03:00 KST. Supabase pg_cron의 기본 시간대(cron.timezone)는 GMT다.
-- 기록: 명령이 지운 대화 수만큼 빈 행을 돌려준다. 그래서 cron.job_run_details.return_message에
--   "N rows"(N = 지운 대화 수)가 남는다. 대화 원문이나 사용자 ID는 남지 않는다.
--   agent_purge_expired를 그대로 부르면 결과가 늘 "1 row"라 지운 수를 알 수 없다(로컬 Supabase 이미지에서 확인).
-- 예약 이름이 같으면 cron.schedule은 기존 예약을 덮어쓴다. 그래서 이 파일을 다시 실행해도 예약은 하나다.
-- 예약은 이 마이그레이션을 실행한 역할(Supabase에서는 postgres)로 돈다. postgres는 함수 소유자라 실행 권한이 있다.

do $$
begin
  if not exists (select 1 from pg_catalog.pg_available_extensions where name = 'pg_cron') then
    raise notice 'pg_cron is not available on this server; skipping the agent-purge-expired schedule';
    return;
  end if;

  -- 문서의 SQL 방법은 이어서 cron 스키마 권한을 postgres에 주라고 한다. 여기서는 그 두 줄을 넣지 않는다.
  -- Supabase는 pg_cron을 만들 때(이미 있어도) 자체 권한 스크립트로 postgres 권한을 맞춘다. 그 위에 같은 grant를
  -- postgres가 다시 실행하면 의존 권한이 생겨, 다음 실행 때 그 스크립트의 revoke가 "dependent privileges exist"로
  -- 실패한다(로컬 Supabase 이미지 17.11.0.004에서 재현).
  create extension if not exists pg_cron with schema pg_catalog;

  perform cron.schedule(
    'agent-purge-expired',
    '0 18 * * *',
    'select from pg_catalog.generate_series(1, public.agent_purge_expired())'
  );
end;
$$;
