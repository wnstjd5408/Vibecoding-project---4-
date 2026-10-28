-- 속도 제한 카운터 (MEG-62, API spec v0.2 1.8·Q-N9, 기술 검토 4절)
-- 서버리스 인스턴스는 메모리를 공유하지 못하고 Vercel Hobby 방화벽은 규칙 1개·IP/JA4 키만 되어
-- 사용자·계정별 제한을 맡지 못한다. 그래서 DB 카운터를 쓴다.
-- 접근 모델은 앞 마이그레이션과 같다: FastAPI(service_role)만 DB에 접근한다.

-- 고정 창(fixed window) 카운터. key는 앱이 해시한 값이라 이메일·IP·사용자 id 원문이 들어가지 않는다.
create table public.rate_limit_counters (
  key text not null,
  window_start timestamptz not null,
  hits integer not null check (hits > 0),
  primary key (key, window_start)
);

-- 오래된 창을 지울 때 쓴다.
create index rate_limit_counters_window_start_idx on public.rate_limit_counters (window_start);

alter table public.rate_limit_counters enable row level security;
revoke all on public.rate_limit_counters from public, anon, authenticated;
grant select, insert, update, delete on public.rate_limit_counters to service_role;

-- 요청 한 건을 세고 한도 안인지 돌려준다. 한도를 넘은 요청도 센다.
-- 창은 에포크 기준으로 window_seconds 단위로 나눈다. 같은 key·창의 동시 요청은 upsert가 직렬화한다.
-- 하루 넘은 창은 호출 중 약 1%에서 같이 지운다(별도 정리 작업을 두지 않고 매 요청 삭제 비용을 피한다).
create function public.rate_limit_hit(p_key text, p_limit integer, p_window_seconds integer)
returns table (allowed boolean, retry_after_seconds integer)
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_now timestamptz := clock_timestamp();
  v_window_start timestamptz;
  v_hits integer;
begin
  -- 창은 하루 이하만 받는다(아래 정리가 하루 넘은 창을 지우므로).
  if p_key is null or p_key = '' or p_limit < 1 or p_window_seconds < 1 or p_window_seconds > 86400 then
    raise exception 'invalid rate limit arguments';
  end if;

  v_window_start := to_timestamp(floor(extract(epoch from v_now) / p_window_seconds) * p_window_seconds);

  insert into public.rate_limit_counters as c (key, window_start, hits)
  values (p_key, v_window_start, 1)
  on conflict (key, window_start) do update set hits = c.hits + 1
  returning c.hits into v_hits;

  if random() < 0.01 then
    delete from public.rate_limit_counters where window_start < v_now - interval '1 day';
  end if;

  allowed := v_hits <= p_limit;
  -- 다음 창이 시작할 때까지 남은 초(올림, 최소 1)
  retry_after_seconds := greatest(
    ceil(extract(epoch from (v_window_start + make_interval(secs => p_window_seconds) - v_now)))::integer,
    1
  );
  return next;
end;
$$;

-- 지금 창에서 센 것 하나를 되돌린다. 로그인 실패 제한처럼 "먼저 세고, 성공하면 되돌리는" 호출이 쓴다.
-- 먼저 세므로 동시 요청이 한도를 넘어 검증까지 가지 못한다(확인만 하고 나중에 세면 동시 요청이 모두 통과한다).
-- 창이 이미 바뀌었거나 행이 없으면 아무 일도 하지 않는다.
create function public.rate_limit_release(p_key text, p_window_seconds integer)
returns void
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_window_start timestamptz;
begin
  if p_key is null or p_key = '' or p_window_seconds < 1 or p_window_seconds > 86400 then
    raise exception 'invalid rate limit arguments';
  end if;

  v_window_start := to_timestamp(floor(extract(epoch from clock_timestamp()) / p_window_seconds) * p_window_seconds);

  -- hits는 1 이상이어야 하므로 1이면 행을 지운다.
  update public.rate_limit_counters set hits = hits - 1
  where key = p_key and window_start = v_window_start and hits > 1;
  if not found then
    delete from public.rate_limit_counters
    where key = p_key and window_start = v_window_start and hits <= 1;
  end if;
end;
$$;

revoke execute on function public.rate_limit_hit(text, integer, integer) from public, anon, authenticated;
grant execute on function public.rate_limit_hit(text, integer, integer) to service_role;
revoke execute on function public.rate_limit_release(text, integer) from public, anon, authenticated;
grant execute on function public.rate_limit_release(text, integer) to service_role;
