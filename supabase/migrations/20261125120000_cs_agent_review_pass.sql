-- CS Agent 2차 점검·보완(D2) 원장 kind와 턴 기록 (MEG-282, 고도화 설계 v0.2 4절, 9절 결정 3~5)
--
-- 1. 원장 kind에 agent_review를 더한다. 2차 호출은 1차(agent)와 다른 키({user_id}:agent-review:{Idempotency-Key}:{attempt_no})를 쓴다.
-- 2. 한도: agent_review는 하루 턴 수 한도에 세지 않는다(앱이 횟수 한도 null로 부른다). 금액 한도와 agent 몫(70%)에는 든다.
--    agent 몫은 agent와 agent_review의 하루 합계로 본다. 횟수 한도는 지금처럼 같은 kind의 첫 시도 행만 센다.
-- 3. ai_turns에 2차 기록 칸(결과 표시, 2차 원장, 2차 프롬프트 버전·규칙 해시)을 더한다. 응답에는 넣지 않는다.
-- 4. agent_finish_turn이 2차 기록을 받는다. 새 인자는 기본값 null이라 이름 인자 호출(E31 취소)은 그대로 같다.
-- 사람이 db push로 적용한다(AI는 원격에 적용하지 않는다).

-- ---------------------------------------------------------------------------
-- 1. 원장 kind
-- ---------------------------------------------------------------------------
alter table public.ai_usage_ledger drop constraint ai_usage_ledger_kind_check;
alter table public.ai_usage_ledger
  add constraint ai_usage_ledger_kind_check check (kind in ('explain', 'quiz', 'followup', 'agent', 'agent_review'));

comment on column public.ai_usage_ledger.idempotency_key is
  'E09 {user_id}:{Idempotency-Key}:{attempt_no} / E11 {user_id}:quiz:{set_id}:{quiz_sets.attempt}:{attempt_no} / E13 {user_id}:followup:{서버 요청 id}:{attempt_no} / E29 {user_id}:agent:{Idempotency-Key}:{attempt_no} / E29 2차 {user_id}:agent-review:{Idempotency-Key}:1';

-- ---------------------------------------------------------------------------
-- 2. 한도 확인: kind 목록과 agent 몫 묶음 (시그니처는 그대로라 권한도 그대로다)
-- ---------------------------------------------------------------------------
create or replace function public.ai_check_limit(
  p_user_id uuid,
  p_kind text,
  p_reserved_usd numeric,
  p_daily_budget_usd numeric,
  p_monthly_budget_usd numeric,
  p_user_daily_share numeric,
  p_user_daily_count_limit integer,
  p_kind_daily_share numeric default null,
  p_attempt_no integer default 1
)
returns boolean
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  v_kst_date date := (now() at time zone 'Asia/Seoul')::date;
  v_kind_share numeric := coalesce(p_kind_daily_share, case when p_kind in ('agent', 'agent_review') then 0.70 end);
  -- kind 몫을 셀 묶음. agent와 agent_review(2차)는 한 묶음으로 70%를 나눠 쓴다(MEG-282 D2).
  v_share_kinds text[] := case when p_kind in ('agent', 'agent_review') then array['agent', 'agent_review']
                               else array[p_kind] end;
  v_month_total numeric;
  v_day_total numeric;
  v_user_total numeric;
  v_kind_total numeric;
  v_user_count integer;
begin
  if p_user_id is null
     or p_kind is null or p_kind not in ('explain', 'quiz', 'followup', 'agent', 'agent_review')
     or p_attempt_no is null or p_attempt_no < 1
     or p_reserved_usd is null or p_reserved_usd < 0
     or p_daily_budget_usd is null or p_daily_budget_usd <= 0
     or p_monthly_budget_usd is null or p_monthly_budget_usd <= 0
     or p_user_daily_share is null or p_user_daily_share <= 0 or p_user_daily_share > 1
     or p_kind_daily_share <= 0 or p_kind_daily_share > 1
     or p_user_daily_count_limit < 1 then
    raise exception 'invalid ai limit arguments';
  end if;

  select
    coalesce(sum(coalesce(l.actual_usd, l.reserved_usd)), 0),
    coalesce(sum(coalesce(l.actual_usd, l.reserved_usd)) filter (where l.kst_date = v_kst_date), 0),
    coalesce(sum(coalesce(l.actual_usd, l.reserved_usd))
             filter (where l.kst_date = v_kst_date and l.user_id = p_user_id), 0),
    coalesce(sum(coalesce(l.actual_usd, l.reserved_usd))
             filter (where l.kst_date = v_kst_date and l.kind = any (v_share_kinds)), 0),
    count(*) filter (where l.kst_date = v_kst_date and l.user_id = p_user_id
                       and l.kind = p_kind and l.attempt_no = 1)
    into v_month_total, v_day_total, v_user_total, v_kind_total, v_user_count
    from public.ai_usage_ledger l
   where l.status in ('reserved', 'settled')
     and l.kst_date between date_trunc('month', v_kst_date)::date and v_kst_date;

  return not (
    v_month_total + p_reserved_usd > p_monthly_budget_usd
    or v_day_total + p_reserved_usd > p_daily_budget_usd
    or v_user_total + p_reserved_usd > p_daily_budget_usd * p_user_daily_share
    or (v_kind_share is not null and v_kind_total + p_reserved_usd > p_daily_budget_usd * v_kind_share)
    or (p_user_daily_count_limit is not null and p_attempt_no = 1
        and v_user_count >= p_user_daily_count_limit)
  );
end;
$$;

-- ---------------------------------------------------------------------------
-- 3. 한도 예약: kind 목록만 바꾼다 (본문은 20261118140000과 같다)
-- ---------------------------------------------------------------------------
create or replace function public.ai_reserve(
  p_user_id uuid,
  p_kind text,
  p_idempotency_key text,
  p_attempt_no integer,
  p_reserved_usd numeric,
  p_daily_budget_usd numeric,
  p_monthly_budget_usd numeric,
  p_user_daily_share numeric,
  p_user_daily_count_limit integer,
  p_kind_daily_share numeric default null
)
returns table (outcome text, ledger_id bigint, ledger_status text)
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_now timestamptz := now();
  v_kst_date date := (now() at time zone 'Asia/Seoul')::date;
begin
  if p_user_id is null
     or p_kind is null or p_kind not in ('explain', 'quiz', 'followup', 'agent', 'agent_review')
     or p_idempotency_key is null or p_idempotency_key = ''
     or p_attempt_no is null or p_attempt_no < 1
     or p_reserved_usd is null or p_reserved_usd < 0
     or p_daily_budget_usd is null or p_daily_budget_usd <= 0
     or p_monthly_budget_usd is null or p_monthly_budget_usd <= 0
     or p_user_daily_share is null or p_user_daily_share <= 0 or p_user_daily_share > 1
     or p_kind_daily_share <= 0 or p_kind_daily_share > 1
     or p_user_daily_count_limit < 1 then
    raise exception 'invalid ai reservation arguments';
  end if;

  perform pg_advisory_xact_lock(hashtextextended('public.ai_reserve', 0));

  update public.ai_usage_ledger
     set status = 'settled', settle_basis = 'reserved_fallback', actual_usd = reserved_usd, settled_at = v_now
   where status = 'reserved' and created_at < v_now - interval '10 minutes';

  select l.id, l.status into ledger_id, ledger_status
    from public.ai_usage_ledger l
   where l.idempotency_key = p_idempotency_key;
  if found then
    outcome := 'exists';
    return next;
    return;
  end if;

  if not public.ai_check_limit(
       p_user_id => p_user_id,
       p_kind => p_kind,
       p_reserved_usd => p_reserved_usd,
       p_daily_budget_usd => p_daily_budget_usd,
       p_monthly_budget_usd => p_monthly_budget_usd,
       p_user_daily_share => p_user_daily_share,
       p_user_daily_count_limit => p_user_daily_count_limit,
       p_kind_daily_share => p_kind_daily_share,
       p_attempt_no => p_attempt_no) then
    outcome := 'limit_reached';
    ledger_id := null;
    ledger_status := null;
    return next;
    return;
  end if;

  insert into public.ai_usage_ledger (user_id, kind, idempotency_key, reserved_usd, attempt_no, kst_date)
  values (p_user_id, p_kind, p_idempotency_key, p_reserved_usd, p_attempt_no, v_kst_date)
  returning id into ledger_id;
  outcome := 'reserved';
  ledger_status := 'reserved';
  return next;
end;
$$;

-- ---------------------------------------------------------------------------
-- 4. 턴의 2차 기록 칸
-- ---------------------------------------------------------------------------
-- review_status: not_applicable(대상 아님), skipped(대상이지만 부르지 않음), unchanged(변경 없음), revised(보완),
-- fallback(2차가 실패해 1차 결과를 씀). null은 이 마이그레이션 전의 턴, 끝나지 않은 턴, 2차 정산 실패·예상 밖 오류로
-- failed가 된 턴이다(그때도 2차를 불렀으면 review_ledger_id와 버전·해시는 남는다).
alter table public.ai_turns
  add column review_status text
    check (review_status in ('not_applicable', 'skipped', 'unchanged', 'revised', 'fallback')),
  add column review_ledger_id bigint references public.ai_usage_ledger (id) on delete set null,
  add column review_prompt_version text,
  add column review_prompt_sha256 text check (review_prompt_sha256 ~ '^[0-9a-f]{64}$');

create index ai_turns_review_ledger_id_idx on public.ai_turns (review_ledger_id) where review_ledger_id is not null;

-- ---------------------------------------------------------------------------
-- 5. 턴 끝내기: 2차 기록 인자 (본문의 나머지는 20261118140000과 같다)
-- ---------------------------------------------------------------------------
drop function public.agent_finish_turn(uuid, uuid, text, text, jsonb, jsonb, bigint, integer, text, text, text);

create function public.agent_finish_turn(
  p_user_id uuid,
  p_turn_id uuid,
  p_status text,
  p_failure text default null,
  p_result jsonb default null,
  p_sources jsonb default null,
  p_ledger_id bigint default null,
  p_paragraph_count integer default null,
  p_model_id text default null,
  p_prompt_version text default null,
  p_retrieval_version text default null,
  p_review_status text default null,
  p_review_ledger_id bigint default null,
  p_review_prompt_version text default null,
  p_review_prompt_sha256 text default null
)
returns boolean
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_now timestamptz := now();
  v_conversation_id uuid;
begin
  if p_user_id is null or p_turn_id is null
     or p_status is null or p_status not in ('completed', 'cancelled', 'failed')
     or (p_status = 'completed') <> (p_result is not null)
     or (p_status = 'failed') <> (p_failure is not null)
     or (p_sources is not null and (p_status <> 'completed' or jsonb_typeof(p_sources) <> 'array'))
     or (p_review_status is not null
         and p_review_status not in ('not_applicable', 'skipped', 'unchanged', 'revised', 'fallback'))
     or (p_review_prompt_sha256 is not null and p_review_prompt_sha256 !~ '^[0-9a-f]{64}$') then
    raise exception 'invalid agent finish arguments';
  end if;

  if p_sources is not null and exists (
       select 1
         from jsonb_to_recordset(p_sources) as s(ref integer, source_kind text, source_id text,
                                                cited_revision text, title text, paragraph_snapshot text)
       having count(*) <> count(distinct s.ref)
           or bool_or(s.ref is null or s.source_kind is null or s.source_kind not in ('note', 'wiki')
                      or s.source_id is null or s.cited_revision is null or s.title is null
                      or s.paragraph_snapshot is null)) then
    raise exception 'invalid agent finish arguments';
  end if;

  -- 원장 연결은 같은 사용자의 agent 행만, 2차 원장은 같은 사용자의 agent_review 행만 받는다.
  if p_ledger_id is not null and not exists (
       select 1 from public.ai_usage_ledger l
        where l.id = p_ledger_id and l.user_id = p_user_id and l.kind = 'agent') then
    raise exception 'invalid agent finish arguments';
  end if;
  if p_review_ledger_id is not null and not exists (
       select 1 from public.ai_usage_ledger l
        where l.id = p_review_ledger_id and l.user_id = p_user_id and l.kind = 'agent_review') then
    raise exception 'invalid agent finish arguments';
  end if;

  select t.conversation_id into v_conversation_id
    from public.ai_turns t
   where t.id = p_turn_id and t.user_id = p_user_id;
  if not found then
    return false;
  end if;
  perform 1 from public.ai_conversations c where c.id = v_conversation_id for update;

  update public.ai_turns t
     set status = p_status,
         failure = p_failure,
         result = p_result,
         ledger_id = coalesce(p_ledger_id, t.ledger_id),
         paragraph_count = coalesce(p_paragraph_count, t.paragraph_count),
         model_id = coalesce(p_model_id, t.model_id),
         prompt_version = coalesce(p_prompt_version, t.prompt_version),
         retrieval_version = coalesce(p_retrieval_version, t.retrieval_version),
         review_status = coalesce(p_review_status, t.review_status),
         review_ledger_id = coalesce(p_review_ledger_id, t.review_ledger_id),
         review_prompt_version = coalesce(p_review_prompt_version, t.review_prompt_version),
         review_prompt_sha256 = coalesce(p_review_prompt_sha256, t.review_prompt_sha256),
         finished_at = v_now
   where t.id = p_turn_id and t.user_id = p_user_id and t.status = 'running'
  returning t.conversation_id into v_conversation_id;

  if not found then
    -- 전이에 실패해도 원장 연결이 아직 없으면 남긴다(비용과 턴을 잇기 위해, spec 9절). 2차 원장도 같다.
    if p_ledger_id is not null then
      update public.ai_turns t
         set ledger_id = p_ledger_id
       where t.id = p_turn_id and t.user_id = p_user_id and t.ledger_id is null;
    end if;
    -- 2차 기록도 함께 남긴다(취소·만료 뒤에도 2차를 불렀는지와 그 버전을 볼 수 있게). 이미 있는 값은 덮어쓰지 않는다.
    if p_review_ledger_id is not null then
      update public.ai_turns t
         set review_ledger_id = p_review_ledger_id,
             review_status = coalesce(t.review_status, p_review_status),
             review_prompt_version = coalesce(t.review_prompt_version, p_review_prompt_version),
             review_prompt_sha256 = coalesce(t.review_prompt_sha256, p_review_prompt_sha256)
       where t.id = p_turn_id and t.user_id = p_user_id and t.review_ledger_id is null;
    end if;
    return false;
  end if;

  if p_sources is not null then
    insert into public.ai_turn_sources (
      turn_id, ref, source_kind, source_id, cited_revision, title, section, excerpt, paragraph_snapshot
    )
    select p_turn_id, s.ref, s.source_kind, s.source_id, s.cited_revision, s.title, s.section, s.excerpt,
           s.paragraph_snapshot
      from jsonb_to_recordset(p_sources) as s(
        ref integer, source_kind text, source_id text, cited_revision text, title text, section text,
        excerpt text, paragraph_snapshot text
      );
  end if;

  update public.ai_conversations set last_active_at = v_now where id = v_conversation_id;
  return true;
end;
$$;

revoke execute on function public.agent_finish_turn(
  uuid, uuid, text, text, jsonb, jsonb, bigint, integer, text, text, text, text, bigint, text, text
) from public, anon, authenticated;
grant execute on function public.agent_finish_turn(
  uuid, uuid, text, text, jsonb, jsonb, bigint, integer, text, text, text, text, bigint, text, text
) to service_role;
