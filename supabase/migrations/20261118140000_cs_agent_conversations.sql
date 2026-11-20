-- CS Agent "AI에게 질문" 대화·턴 저장과 원장 agent kind (MEG-232, 기술 검토 v0.4 5절, API spec v0.2 3·9절)
-- 추가만 한다. 기존 행을 바꾸거나 지우지 않는다(기술 검토 0절 결론 2).
-- 접근 모델은 앞 마이그레이션과 같다: FastAPI(service_role)만 DB에 접근한다. 새 테이블은 RLS를 켜고 정책을 두지 않는다.
-- 금액·단가는 쓰지 않는다. 앱이 환경변수에서 읽어 인자로 넘긴다(2026-11-02 사람 결정).
-- 비율·길이·기간 값의 근거:
--   agent 금액 몫 70%: D4(사용자 결정 2026-11-18, 시작값. T3 실측 뒤 다시 정한다)
--   대화 보관 7일, 기준은 마지막 활동: Q3(사용자 결정 2026-11-16)
--   질문 1,000자, 선택 문맥 2,000자: Q4 임시값(T3 실측에서 확정)
-- 외래키 삭제 규칙은 2026-11-18 사용자 결정(MEG-232 댓글)이다.

-- ---------------------------------------------------------------------------
-- 1. 대화 (spec 3절 conversation, E27)
-- ---------------------------------------------------------------------------
create table public.ai_conversations (
  id uuid primary key default gen_random_uuid(),
  -- 사용자를 지우면 그 사용자의 대화도 지운다.
  user_id uuid not null references public.profiles (user_id) on delete cascade,
  origin text not null check (origin in ('note', 'wiki', 'none')),
  -- 노트가 지워지면 대화를 닫는다(디자인 결정 3).
  note_id bigint references public.notes (id) on delete cascade,
  note_revision integer check (note_revision >= 1),
  -- 위키 문맥의 형태는 Q1(MEG-163)에서 정한다. 그때까지 문자열로 둔다.
  wiki_ref text check (wiki_ref is null or char_length(wiki_ref) between 1 and 1000),
  -- origin none이면 비워 두고 첫 질문으로 채운다(Q9). 위키 제목을 쓸 수 있어 노트 제목 상한(300자)과 맞춘다.
  topic_label text not null default '' check (char_length(topic_label) <= 300),
  created_at timestamptz not null default now(),
  -- 턴을 선점하거나 끝낼 때 갱신한다. 7일 보관 정리(agent_purge_expired)의 기준이다.
  last_active_at timestamptz not null default now(),
  -- 턴의 (conversation_id, user_id) 복합 외래키가 가리킨다. 턴의 사용자와 대화의 주인이 어긋나지 못하게 한다.
  unique (id, user_id),
  check (
    (origin = 'note' and note_id is not null and note_revision is not null and wiki_ref is null)
    or (origin = 'wiki' and note_id is null and note_revision is null and wiki_ref is not null)
    or (origin = 'none' and note_id is null and note_revision is null and wiki_ref is null)
  )
);

create index ai_conversations_user_id_idx on public.ai_conversations (user_id);
create index ai_conversations_last_active_at_idx on public.ai_conversations (last_active_at);
create index ai_conversations_note_id_idx on public.ai_conversations (note_id) where note_id is not null;

-- ---------------------------------------------------------------------------
-- 2. 선택 문맥 (spec 3절 selection, 선택 문맥 저장)
-- ---------------------------------------------------------------------------
-- 받을 때 자른 원문과 그때의 개정을 저장하고, 이후 턴은 저장한 원문을 쓴다. 제외는 excluded_at으로 남긴다.
-- start·end는 E09와 같은 위치 규칙이다(유니코드 코드포인트, 시작 포함·끝 제외). end는 예약어라 따옴표로 쓴다.
create table public.ai_conversation_selections (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.ai_conversations (id) on delete cascade,
  note_id bigint not null references public.notes (id) on delete cascade,
  note_revision integer not null check (note_revision >= 1),
  start integer not null check (start >= 0),
  "end" integer not null,
  text_snapshot text not null check (char_length(text_snapshot) between 1 and 2000),
  excluded_at timestamptz,
  created_at timestamptz not null default now(),
  check ("end" > start)
);

create index ai_conversation_selections_conversation_id_idx on public.ai_conversation_selections (conversation_id);
create index ai_conversation_selections_note_id_idx on public.ai_conversation_selections (note_id);

-- ---------------------------------------------------------------------------
-- 3. 턴 (spec 3절 turn, 3.1, E29 2단계, 9절 실행 기록)
-- ---------------------------------------------------------------------------
-- 상태 전이는 status = 'running'일 때만 바꾸는 조건부 갱신이다(spec 3.1). running은 lease_expires_at까지 갱신되지
-- 않으면 만료로 보고 failed(interrupted)로 바꾼다. hidden(가림)은 열로 두지 않고 읽을 때 계산한다(spec 8절).
-- 실행 중 step·paragraph_count·lease_expires_at 갱신(T3)과 읽을 때의 만료 처리(T2)는 앱이 직접 UPDATE하되,
-- 반드시 status = 'running' 조건을 붙인다. 끝난 턴을 되살리거나 덮어쓰지 않기 위해서다.
create table public.ai_turns (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null,
  user_id uuid not null references public.profiles (user_id) on delete cascade,
  -- 대화 안 순서. agent_claim_turn이 대화 행을 잠근 뒤 정한다.
  seq integer not null check (seq >= 1),
  -- 클라이언트가 보내는 Idempotency-Key(UUID). 사용자별로 구분한다(spec 2절).
  idempotency_key uuid not null,
  question_kind text not null check (question_kind in ('free', 'suggested', 'preset')),
  -- preset은 서버가 바꾼 고정 문구를 담는다.
  question_text text not null check (char_length(question_text) between 1 and 1000),
  preset text check (preset in ('detail', 'simple', 'example')),
  -- 추천 질문을 고른 앞 턴. 그 턴이 지워져도 이 턴은 남긴다.
  from_turn_id uuid references public.ai_turns (id) on delete set null,
  -- 앞 턴의 확인 질문에 대한 답(의미 확인·주제 전환 확인).
  reply jsonb,
  -- '같은 질문 다시 하기'의 대상 턴.
  retry_of_turn_id uuid references public.ai_turns (id) on delete set null,
  status text not null default 'running' check (status in ('running', 'completed', 'cancelled', 'failed')),
  failure text check (failure in ('error', 'interrupted', 'limit')),
  step text check (step in ('understand', 'retrieve', 'compose')),
  paragraph_count integer check (paragraph_count >= 0),
  -- completed일 때만 있다(spec 5절 turn.result). 중단·실패한 턴은 결과를 저장하지 않는다.
  result jsonb,
  -- 원장 행은 지우지 않지만, 지워지더라도 턴은 남긴다. 응답에는 넣지 않는다(spec 9절).
  ledger_id bigint references public.ai_usage_ledger (id) on delete set null,
  -- 실행 기록(spec 9절). 응답에는 넣지 않는다.
  model_id text,
  prompt_version text,
  retrieval_version text,
  lease_expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  finished_at timestamptz,
  -- 대화를 지우면 턴도 지운다. 턴의 사용자는 대화의 주인과 같아야 한다.
  foreign key (conversation_id, user_id) references public.ai_conversations (id, user_id) on delete cascade,
  unique (user_id, idempotency_key),
  unique (conversation_id, seq),
  check ((question_kind = 'preset') = (preset is not null)),
  check ((status = 'failed') = (failure is not null)),
  check ((status = 'completed') = (result is not null)),
  check ((status = 'running') = (finished_at is null))
);

-- 한 대화에 진행 중인 턴은 하나뿐이다(spec 핵심 규칙 2, AG08).
create unique index ai_turns_one_running_per_conversation_idx
  on public.ai_turns (conversation_id)
  where status = 'running';
create index ai_turns_ledger_id_idx on public.ai_turns (ledger_id) where ledger_id is not null;
create index ai_turns_from_turn_id_idx on public.ai_turns (from_turn_id) where from_turn_id is not null;
create index ai_turns_retry_of_turn_id_idx on public.ai_turns (retry_of_turn_id) where retry_of_turn_id is not null;

-- ---------------------------------------------------------------------------
-- 4. 턴 출처 (spec 5.2, E32, 기술 검토 5.1)
-- ---------------------------------------------------------------------------
-- 답변이 인용한 문단만 담는다. 노트 출처(source_kind note)는 노트를 지워도 행을 남기고, 가림 함수가 회수로 판단한다.
-- paragraph_snapshot은 인용 당시 문단 원문이다. 노트는 이전 개정을 보관하지 않는다.
create table public.ai_turn_sources (
  turn_id uuid not null references public.ai_turns (id) on delete cascade,
  -- 답변 안의 인용 번호 [n]
  ref integer not null check (ref >= 1),
  source_kind text not null check (source_kind in ('note', 'wiki')),
  source_id text not null check (char_length(source_id) between 1 and 200),
  cited_revision text not null check (char_length(cited_revision) between 1 and 200),
  title text not null check (char_length(title) between 1 and 300),
  section text,
  excerpt text,
  paragraph_snapshot text not null check (char_length(paragraph_snapshot) between 1 and 20000),
  primary key (turn_id, ref)
);

-- ---------------------------------------------------------------------------
-- 5. 원장 kind에 agent 추가 (spec 9절)
-- ---------------------------------------------------------------------------
-- 잠금이 잠시 생기지만 원장 행 수가 적어 영향이 작다(기술 검토 5.4 위험 2).
alter table public.ai_usage_ledger drop constraint ai_usage_ledger_kind_check;
alter table public.ai_usage_ledger
  add constraint ai_usage_ledger_kind_check check (kind in ('explain', 'quiz', 'followup', 'agent'));

comment on column public.ai_usage_ledger.idempotency_key is
  'E09 {user_id}:{Idempotency-Key}:{attempt_no} / E11 {user_id}:quiz:{set_id}:{quiz_sets.attempt}:{attempt_no} / E13 {user_id}:followup:{서버 요청 id}:{attempt_no} / E29 {user_id}:agent:{Idempotency-Key}:{attempt_no}';

-- ---------------------------------------------------------------------------
-- 6. 한도 확인 (읽기 전용, E29 3단계) — ai_reserve도 이 함수로 한도를 판정한다
-- ---------------------------------------------------------------------------
-- 예약하지 않고, 이 금액을 지금 예약하면 한도 안인지만 돌려준다(true = 한도 안).
-- 합계는 settled 행의 실제 금액과 reserved 행의 예약액을 더한다. released 행은 세지 않는다.
-- 10분 넘은 reserved 행도 예약액으로 세므로, ai_reserve가 먼저 정산해도 합계는 같다.
-- kind 몫(p_kind_daily_share)은 그 kind의 하루 합계(모든 사용자)가 하루 예산의 몫을 넘지 못하게 한다(Q5).
-- 인자가 null이면 agent는 0.70(D4), 다른 kind는 몫 검사가 없다(기존 동작 그대로).
-- 횟수 한도는 첫 시도(p_attempt_no = 1)에만 적용하고 같은 kind의 첫 시도 행만 센다.
create function public.ai_check_limit(
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
  v_kind_share numeric := coalesce(p_kind_daily_share, case when p_kind = 'agent' then 0.70 end);
  v_month_total numeric;
  v_day_total numeric;
  v_user_total numeric;
  v_kind_total numeric;
  v_user_count integer;
begin
  if p_user_id is null
     or p_kind is null or p_kind not in ('explain', 'quiz', 'followup', 'agent')
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
             filter (where l.kst_date = v_kst_date and l.kind = p_kind), 0),
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
-- 7. 한도 예약 교체 (기술 검토 5.4 위험 1)
-- ---------------------------------------------------------------------------
-- 오버로드하지 않도록 기존 9개 인자 함수를 지우고 새 시그니처로 만든다. 새 인자(p_kind_daily_share)는 기본값 null이라
-- 앱의 이름 인자 RPC 호출은 그대로 같은 결과를 낸다. ai_claim_quiz_set의 호출은 아래 8절에서 이름 인자로 바꾼다.
-- 이 파일은 한 트랜잭션으로 적용되므로 drop과 create 사이에 함수가 없는 순간이 밖에서 보이지 않는다.
-- outcome: reserved(행을 넣음), limit_reached(행도 호출도 없음), exists(같은 멱등 키 행이 이미 있음).
-- 한도 판정은 ai_check_limit과 같은 규칙을 쓴다(아래에서 호출).
drop function public.ai_reserve(uuid, text, text, integer, numeric, numeric, numeric, numeric, integer);

create function public.ai_reserve(
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
     or p_kind is null or p_kind not in ('explain', 'quiz', 'followup', 'agent')
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

  -- 모든 예약을 한 줄로 세운다. 합계를 읽고 넣는 사이에 다른 예약이 끼지 못해 동시 요청이 한도를 함께 넘지 못한다.
  -- 잠금은 트랜잭션이 끝나면 풀린다.
  perform pg_advisory_xact_lock(hashtextextended('public.ai_reserve', 0));

  -- 10분 넘게 reserved로 남은 행은 과금 여부를 모르므로 예약액 그대로 정산한다(spec v0.2 5.3절 6번).
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

  -- 잠금을 잡은 뒤의 새 문장이라 다른 트랜잭션이 커밋한 예약까지 보고 판정한다.
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
-- 8. 퀴즈 세트 선점: ai_reserve 호출을 이름 인자로 고친다 (기술 검토 5.4 위험 1)
-- ---------------------------------------------------------------------------
-- 본문은 20261102120000_ai_ledger_functions.sql과 같고, ai_reserve 호출만 이름 인자로 바꿨다.
-- 퀴즈는 kind 몫 검사를 받지 않는다(p_kind_daily_share null).
create or replace function public.ai_claim_quiz_set(
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
        p_user_id => p_user_id,
        p_kind => 'quiz',
        p_idempotency_key => format('%s:quiz:%s:%s:1', p_user_id, set_id, attempt),
        p_attempt_no => 1,
        p_reserved_usd => p_reserved_usd,
        p_daily_budget_usd => p_daily_budget_usd,
        p_monthly_budget_usd => p_monthly_budget_usd,
        p_user_daily_share => p_user_daily_share,
        p_user_daily_count_limit => null,
        p_kind_daily_share => null
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
-- 9. 턴 선점 (E29 2단계, spec 3.1 만료)
-- ---------------------------------------------------------------------------
-- 한 트랜잭션으로: 대화 행 잠금 → 이 대화의 만료 턴 정리 → 같은 키 확인 → 진행 중 확인 → 턴 기록.
-- outcome:
--   existing     같은 사용자·같은 키의 턴이 있다(다른 대화여도). turn_status로 진행 중인지 끝났는지 알린다.
--   in_progress  이 대화에 다른 키의 running 턴이 있다. turn_id는 그 턴이다.
--   claimed      새 턴을 running으로 기록했다.
-- 대화가 없거나 이 사용자의 것이 아니면 SQLSTATE MEG02(conversation_not_found)를 낸다. 앱은 404로 돌려준다.
-- 대화 소유·노트 권한·질문 형식 확인(E29 1단계)은 앱이 먼저 한다.
create function public.agent_claim_turn(
  p_user_id uuid,
  p_conversation_id uuid,
  p_idempotency_key uuid,
  p_question_kind text,
  p_question_text text,
  p_lease_seconds integer,
  p_preset text default null,
  p_from_turn_id uuid default null,
  p_reply jsonb default null,
  p_retry_of_turn_id uuid default null
)
returns table (outcome text, turn_id uuid, seq integer, turn_status text)
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_now timestamptz := now();
begin
  if p_user_id is null or p_conversation_id is null or p_idempotency_key is null
     or p_question_kind is null or p_question_text is null
     or p_lease_seconds is null or p_lease_seconds < 1 then
    raise exception 'invalid agent claim arguments';
  end if;

  -- 같은 대화의 선점을 한 줄로 세운다. seq와 진행 중 확인이 이 잠금 아래에서 정해진다.
  perform 1
    from public.ai_conversations c
   where c.id = p_conversation_id and c.user_id = p_user_id
     for update;
  if not found then
    raise exception using errcode = 'MEG02', message = 'conversation_not_found';
  end if;

  -- 만료된 running 턴은 실행이 죽은 것으로 보고 끝낸다(spec 3.1). 이 대화의 턴과, 다른 대화에 있을 수 있는
  -- 같은 키의 턴이 대상이다.
  update public.ai_turns t
     set status = 'failed', failure = 'interrupted', finished_at = v_now
   where t.status = 'running' and t.lease_expires_at <= v_now
     and (t.conversation_id = p_conversation_id
          or (t.user_id = p_user_id and t.idempotency_key = p_idempotency_key));

  select t.id, t.seq, t.status into turn_id, seq, turn_status
    from public.ai_turns t
   where t.user_id = p_user_id and t.idempotency_key = p_idempotency_key;
  if found then
    outcome := 'existing';
    return next;
    return;
  end if;

  select t.id, t.seq, t.status into turn_id, seq, turn_status
    from public.ai_turns t
   where t.conversation_id = p_conversation_id and t.status = 'running';
  if found then
    outcome := 'in_progress';
    return next;
    return;
  end if;

  -- 추천 질문의 앞 턴과 다시 묻기 대상 턴은 같은 대화(같은 사용자)의 턴이어야 한다. 다른 사용자의 턴을 문맥으로
  -- 끌어오지 못하게 한다.
  if (p_from_turn_id is not null and not exists (
        select 1 from public.ai_turns t where t.id = p_from_turn_id and t.conversation_id = p_conversation_id))
     or (p_retry_of_turn_id is not null and not exists (
        select 1 from public.ai_turns t where t.id = p_retry_of_turn_id and t.conversation_id = p_conversation_id)) then
    raise exception 'invalid agent claim arguments';
  end if;

  begin
    insert into public.ai_turns (
      conversation_id, user_id, seq, idempotency_key, question_kind, question_text, preset,
      from_turn_id, reply, retry_of_turn_id, lease_expires_at
    )
    values (
      p_conversation_id, p_user_id,
      (select coalesce(max(t.seq), 0) + 1 from public.ai_turns t where t.conversation_id = p_conversation_id),
      p_idempotency_key, p_question_kind, p_question_text, p_preset,
      p_from_turn_id, p_reply, p_retry_of_turn_id, v_now + make_interval(secs => p_lease_seconds)
    )
    returning id, ai_turns.seq, status into turn_id, seq, turn_status;
  exception
    -- 같은 키가 다른 대화에서 동시에 선점된 경우다. 그 트랜잭션이 커밋된 뒤라 새 문장에서 보인다.
    when unique_violation then
      select t.id, t.seq, t.status into turn_id, seq, turn_status
        from public.ai_turns t
       where t.user_id = p_user_id and t.idempotency_key = p_idempotency_key;
      if not found then
        raise;
      end if;
      outcome := 'existing';
      return next;
      return;
  end;

  update public.ai_conversations set last_active_at = v_now where id = p_conversation_id;
  outcome := 'claimed';
  return next;
end;
$$;

-- ---------------------------------------------------------------------------
-- 10. 턴 끝내기 (spec 3.1 조건부 전이, E29 10단계, E31)
-- ---------------------------------------------------------------------------
-- status = 'running'인 이 사용자의 턴만 바꾼다. 바꿨으면 true를 돌려준다.
-- 이미 cancelled·failed가 된 턴에 completed를 쓰지 못한다. 그때 결과와 출처는 버리고 정산은 그대로 둔다.
-- p_ledger_id는 전이에 실패해도, 턴에 원장 연결이 아직 없으면 기록한다(비용과 턴을 잇기 위해, spec 9절).
-- p_sources는 completed일 때만 넣는다. 형태: [{ref, source_kind, source_id, cited_revision, title, section?,
-- excerpt?, paragraph_snapshot}]
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
  p_retrieval_version text default null
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
     or (p_sources is not null and (p_status <> 'completed' or jsonb_typeof(p_sources) <> 'array')) then
    raise exception 'invalid agent finish arguments';
  end if;

  -- 출처 형태(필수 필드, 종류, ref 중복)를 상태를 바꾸기 전에 확인한다. 열 길이 상한은 앱이 먼저 맞춘다(T3).
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

  -- 원장 연결은 같은 사용자의 agent 행만 받는다.
  if p_ledger_id is not null and not exists (
       select 1 from public.ai_usage_ledger l
        where l.id = p_ledger_id and l.user_id = p_user_id and l.kind = 'agent') then
    raise exception 'invalid agent finish arguments';
  end if;

  -- agent_claim_turn과 같은 순서(대화 행 → 턴 행)로 잠가 교착을 막는다.
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
         finished_at = v_now
   where t.id = p_turn_id and t.user_id = p_user_id and t.status = 'running'
  returning t.conversation_id into v_conversation_id;

  if not found then
    if p_ledger_id is not null then
      update public.ai_turns t
         set ledger_id = p_ledger_id
       where t.id = p_turn_id and t.user_id = p_user_id and t.ledger_id is null;
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

-- ---------------------------------------------------------------------------
-- 11. 7일 보관 정리 (Q3)
-- ---------------------------------------------------------------------------
-- 마지막 활동이 7일 지난 대화를 지운다. 선택 문맥·턴·출처는 외래키 cascade로 함께 지워진다.
-- 원장 행은 비용 기록이라 지우지 않는다(턴 쪽 외래키만 사라진다). 지운 대화 수를 돌려준다.
-- 하루 한 번 부르는 예약 작업은 T5(MEG-235)에서 만든다.
create function public.agent_purge_expired()
returns integer
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_count integer;
begin
  delete from public.ai_conversations c
   where c.last_active_at < now() - interval '7 days';
  get diagnostics v_count = row_count;
  return v_count;
end;
$$;

-- ---------------------------------------------------------------------------
-- 12. 보안: RLS를 켜고 정책은 만들지 않는다. 테이블과 함수는 service_role만 쓴다.
-- ---------------------------------------------------------------------------
alter table public.ai_conversations enable row level security;
alter table public.ai_conversation_selections enable row level security;
alter table public.ai_turns enable row level security;
alter table public.ai_turn_sources enable row level security;

revoke all on table
  public.ai_conversations, public.ai_conversation_selections, public.ai_turns, public.ai_turn_sources
  from anon, authenticated;
grant select, insert, update, delete on table
  public.ai_conversations, public.ai_conversation_selections, public.ai_turns, public.ai_turn_sources
  to service_role;

revoke execute on function public.ai_check_limit(uuid, text, numeric, numeric, numeric, numeric, integer, numeric, integer)
  from public, anon, authenticated;
grant execute on function public.ai_check_limit(uuid, text, numeric, numeric, numeric, numeric, integer, numeric, integer)
  to service_role;
revoke execute on function public.ai_reserve(uuid, text, text, integer, numeric, numeric, numeric, numeric, integer, numeric)
  from public, anon, authenticated;
grant execute on function public.ai_reserve(uuid, text, text, integer, numeric, numeric, numeric, numeric, integer, numeric)
  to service_role;
revoke execute on function public.ai_claim_quiz_set(uuid, date, date, numeric, numeric, numeric, numeric, integer, integer)
  from public, anon, authenticated;
grant execute on function public.ai_claim_quiz_set(uuid, date, date, numeric, numeric, numeric, numeric, integer, integer)
  to service_role;
revoke execute on function public.agent_claim_turn(uuid, uuid, uuid, text, text, integer, text, uuid, jsonb, uuid)
  from public, anon, authenticated;
grant execute on function public.agent_claim_turn(uuid, uuid, uuid, text, text, integer, text, uuid, jsonb, uuid)
  to service_role;
revoke execute on function public.agent_finish_turn(uuid, uuid, text, text, jsonb, jsonb, bigint, integer, text, text, text)
  from public, anon, authenticated;
grant execute on function public.agent_finish_turn(uuid, uuid, text, text, jsonb, jsonb, bigint, integer, text, text, text)
  to service_role;
revoke execute on function public.agent_purge_expired() from public, anon, authenticated;
grant execute on function public.agent_purge_expired() to service_role;
