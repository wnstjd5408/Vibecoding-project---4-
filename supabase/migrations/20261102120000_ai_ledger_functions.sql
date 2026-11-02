-- AI 공통 계층 SQL 함수 (MEG-86, API spec v0.2 5.3·5.4·5.7·6.4, Q-N1)
-- 한도 예약·정산, 퀴즈 세트 선점, AI 설명 무효화. 여러 문장을 한 트랜잭션으로 묶어야 해서 SQL 함수로 둔다.
-- 접근 모델은 앞 마이그레이션과 같다: FastAPI(service_role)만 DB에 접근한다.
-- 예산·단가 금액은 공개 저장소에 쓰지 않는다. 앱이 환경변수에서 읽어 인자로 넘긴다(2026-11-02 사람 결정).
-- 10분(오래된 예약 정산), 선점 5분·2회, 사용자별 N과 한 사용자 몫은 API spec의 제안값이다(Q3에서 확정).

-- ---------------------------------------------------------------------------
-- 1. 한도 예약 (5.3절 2·6번)
-- ---------------------------------------------------------------------------
-- outcome: reserved(행을 넣음), limit_reached(행도 호출도 없음), exists(같은 멱등 키 행이 이미 있음).
-- 합계는 settled 행의 실제 금액과 reserved 행의 예약액을 더한다. released 행은 세지 않는다.
-- 사용자별 횟수(p_user_daily_count_limit)는 같은 kind의 첫 시도(attempt_no = 1)만 센다. 호출 안 재시도는 횟수에서 빠지고
-- 금액 한도에는 걸린다. null이면 횟수 제한이 없다(퀴즈·꼬리 질문).
create function public.ai_reserve(
  p_user_id uuid,
  p_kind text,
  p_idempotency_key text,
  p_attempt_no integer,
  p_reserved_usd numeric,
  p_daily_budget_usd numeric,
  p_monthly_budget_usd numeric,
  p_user_daily_share numeric,
  p_user_daily_count_limit integer
)
returns table (outcome text, ledger_id bigint, ledger_status text)
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_now timestamptz := now();
  v_kst_date date := (now() at time zone 'Asia/Seoul')::date;
  v_month_total numeric;
  v_day_total numeric;
  v_user_total numeric;
  v_user_count integer;
begin
  if p_user_id is null
     or p_kind is null or p_kind not in ('explain', 'quiz', 'followup')
     or p_idempotency_key is null or p_idempotency_key = ''
     or p_attempt_no is null or p_attempt_no < 1
     or p_reserved_usd is null or p_reserved_usd < 0
     or p_daily_budget_usd is null or p_daily_budget_usd <= 0
     or p_monthly_budget_usd is null or p_monthly_budget_usd <= 0
     or p_user_daily_share is null or p_user_daily_share <= 0 or p_user_daily_share > 1
     or p_user_daily_count_limit < 1 then
    raise exception 'invalid ai reservation arguments';
  end if;

  -- 모든 예약을 한 줄로 세운다. 합계를 읽고 넣는 사이에 다른 예약이 끼지 못해 동시 요청이 한도를 함께 넘지 못한다.
  -- 잠금은 트랜잭션이 끝나면 풀린다.
  perform pg_advisory_xact_lock(hashtextextended('public.ai_reserve', 0));

  -- 10분 넘게 reserved로 남은 행은 과금 여부를 모르므로 예약액 그대로 정산한다(5.3절 6번).
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

  select
    coalesce(sum(coalesce(l.actual_usd, l.reserved_usd)), 0),
    coalesce(sum(coalesce(l.actual_usd, l.reserved_usd)) filter (where l.kst_date = v_kst_date), 0),
    coalesce(sum(coalesce(l.actual_usd, l.reserved_usd))
             filter (where l.kst_date = v_kst_date and l.user_id = p_user_id), 0),
    count(*) filter (where l.kst_date = v_kst_date and l.user_id = p_user_id
                       and l.kind = p_kind and l.attempt_no = 1)
    into v_month_total, v_day_total, v_user_total, v_user_count
    from public.ai_usage_ledger l
   where l.status in ('reserved', 'settled')
     and l.kst_date between date_trunc('month', v_kst_date)::date and v_kst_date;

  if v_month_total + p_reserved_usd > p_monthly_budget_usd
     or v_day_total + p_reserved_usd > p_daily_budget_usd
     or v_user_total + p_reserved_usd > p_daily_budget_usd * p_user_daily_share
     or (p_user_daily_count_limit is not null and p_attempt_no = 1
         and v_user_count >= p_user_daily_count_limit) then
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
-- 2. 정산 (5.3절 4번)
-- ---------------------------------------------------------------------------
-- p_outcome: usage(응답 usage로 정산, 금액·토큰 필수), reserved_fallback(과금 여부를 몰라 예약액 그대로),
-- released(과금되지 않았음이 확실함). reserved 상태인 행만 바꾸고, 바꿨으면 true를 돌려준다.
-- 이미 끝난 행(다음 예약이 10분 넘었다고 reserved_fallback으로 정산한 행 등)은 그대로 두어 비용을 한 번만 센다.
create function public.ai_settle(
  p_ledger_id bigint,
  p_outcome text,
  p_actual_usd numeric,
  p_input_tokens integer,
  p_output_tokens integer
)
returns boolean
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if p_ledger_id is null or p_outcome is null then
    raise exception 'invalid ai settlement arguments';
  end if;

  if p_outcome = 'usage' then
    if p_actual_usd is null or p_actual_usd < 0
       or p_input_tokens is null or p_input_tokens < 0
       or p_output_tokens is null or p_output_tokens < 0 then
      raise exception 'invalid ai settlement arguments';
    end if;
    update public.ai_usage_ledger
       set status = 'settled', settle_basis = 'usage', actual_usd = p_actual_usd,
           input_tokens = p_input_tokens, output_tokens = p_output_tokens, settled_at = now()
     where id = p_ledger_id and status = 'reserved';
  elsif p_outcome = 'reserved_fallback' then
    update public.ai_usage_ledger
       set status = 'settled', settle_basis = 'reserved_fallback', actual_usd = reserved_usd, settled_at = now()
     where id = p_ledger_id and status = 'reserved';
  elsif p_outcome = 'released' then
    update public.ai_usage_ledger
       set status = 'released'
     where id = p_ledger_id and status = 'reserved';
  else
    raise exception 'invalid ai settlement arguments';
  end if;

  return found;
end;
$$;

-- ---------------------------------------------------------------------------
-- 3. 퀴즈 세트 선점 (6.4절 2~5번)
-- ---------------------------------------------------------------------------
-- 선점과 첫 예약을 한 트랜잭션으로 한다. 예약이 한도로 실패하면 선점(새 행 포함)도 되돌린다.
-- outcome: claimed(선점하고 첫 예약까지 함), ready(이미 만들어짐), generating(다른 요청이 선점 중),
-- failed(시도를 다 씀, AI 없음), limit_reached(한도, 선점 없음).
-- 첫 예약의 멱등 키는 {user_id}:quiz:{set_id}:{attempt}:1이다(v06 주석). 재시도(attempt_no 2)는 앱이 ai_reserve로 한다.
-- 대상 용어 확인(6.4절 1번)과 결과 저장(7번)은 E11이 한다.
create function public.ai_claim_quiz_set(
  p_user_id uuid,
  p_quiz_date date,
  p_source_date date,
  p_reserved_usd numeric,
  p_daily_budget_usd numeric,
  p_monthly_budget_usd numeric,
  p_user_daily_share numeric,
  p_lease_seconds integer,
  p_max_attempts integer
)
returns table (outcome text, set_id bigint, attempt integer, ledger_id bigint)
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_status text;
  v_lease timestamptz;
  v_reserve record;
begin
  if p_user_id is null or p_quiz_date is null or p_source_date is null
     or p_lease_seconds is null or p_lease_seconds < 1
     or p_max_attempts is null or p_max_attempts < 1 then
    raise exception 'invalid quiz claim arguments';
  end if;

  begin
    insert into public.quiz_sets (user_id, quiz_date, source_date)
    values (p_user_id, p_quiz_date, p_source_date)
    on conflict (user_id, quiz_date) do nothing;

    select q.id, q.status, q.lease_expires_at, q.attempt
      into set_id, v_status, v_lease, attempt
      from public.quiz_sets q
     where q.user_id = p_user_id and q.quiz_date = p_quiz_date
       for update;

    if v_status = 'ready' then
      outcome := 'ready';
      return next;
      return;
    end if;
    -- 방금 만든 행은 attempt 0에 선점 만료 시각이 없다. 그 밖의 generating은 만료 전이면 다른 요청이 만드는 중이다.
    if v_status = 'generating' and v_lease is not null and v_lease > now() then
      outcome := 'generating';
      return next;
      return;
    end if;
    if attempt >= p_max_attempts then
      update public.quiz_sets set status = 'failed', lease_expires_at = null
       where id = set_id and status <> 'failed';
      outcome := 'failed';
      return next;
      return;
    end if;

    attempt := attempt + 1;
    update public.quiz_sets
       set status = 'generating', lease_expires_at = now() + make_interval(secs => p_lease_seconds),
           attempt = ai_claim_quiz_set.attempt
     where id = set_id;

    select r.outcome, r.ledger_id into v_reserve
      from public.ai_reserve(
        p_user_id, 'quiz', format('%s:quiz:%s:%s:1', p_user_id, set_id, attempt), 1,
        p_reserved_usd, p_daily_budget_usd, p_monthly_budget_usd, p_user_daily_share, null
      ) r;
    if v_reserve.outcome = 'limit_reached' then
      raise exception using errcode = 'MEG01', message = 'ai_limit_reached';
    end if;
    if v_reserve.outcome <> 'reserved' then
      -- 새 선점 번호의 키가 이미 있을 수 없다. 있으면 상태가 어긋난 것이다.
      raise exception 'quiz reservation key already exists';
    end if;
    ledger_id := v_reserve.ledger_id;
    outcome := 'claimed';
    return next;
  exception
    when sqlstate 'MEG01' then
      outcome := 'limit_reached';
      set_id := null;
      attempt := null;
      ledger_id := null;
      return next;
  end;
end;
$$;

-- ---------------------------------------------------------------------------
-- 4. AI 설명 무효화 (5.7절)
-- ---------------------------------------------------------------------------
-- 노트(revision 증가·비공개 전환·삭제), 용어(사전 등록), 설명 하나(신고 처리) 중 정확히 하나를 받는다.
-- 행은 지우지 않고 invalidated_at만 채운다. 무효화한 행 수를 돌려준다.
-- 노트·사전 쓰기 함수가 같은 트랜잭션 안에서 부른다(S14).
create function public.ai_invalidate_explanations(
  p_note_id bigint,
  p_term_id bigint,
  p_explanation_id bigint
)
returns integer
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_count integer;
begin
  if num_nonnulls(p_note_id, p_term_id, p_explanation_id) <> 1 then
    raise exception 'exactly one invalidation target is required';
  end if;

  update public.ai_explanations
     set invalidated_at = now()
   where invalidated_at is null
     and (note_id = p_note_id or term_id = p_term_id or id = p_explanation_id);

  get diagnostics v_count = row_count;
  return v_count;
end;
$$;

revoke execute on function public.ai_reserve(uuid, text, text, integer, numeric, numeric, numeric, numeric, integer)
  from public, anon, authenticated;
grant execute on function public.ai_reserve(uuid, text, text, integer, numeric, numeric, numeric, numeric, integer)
  to service_role;
revoke execute on function public.ai_settle(bigint, text, numeric, integer, integer) from public, anon, authenticated;
grant execute on function public.ai_settle(bigint, text, numeric, integer, integer) to service_role;
revoke execute on function public.ai_claim_quiz_set(uuid, date, date, numeric, numeric, numeric, numeric, integer, integer)
  from public, anon, authenticated;
grant execute on function public.ai_claim_quiz_set(uuid, date, date, numeric, numeric, numeric, numeric, integer, integer)
  to service_role;
revoke execute on function public.ai_invalidate_explanations(bigint, bigint, bigint) from public, anon, authenticated;
grant execute on function public.ai_invalidate_explanations(bigint, bigint, bigint) to service_role;
