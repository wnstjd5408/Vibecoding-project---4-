-- E11 퀴즈 세트 저장 (MEG-91, API spec v0.2 6.4절 7번)
--
-- AI가 만든 문항을 저장하고 세트를 ready로 바꾼다. 후보 스냅샷(quiz_set_terms)·문항(quiz_items)·상태 전환이 한 트랜잭션이다.
-- 세트 행을 for update로 잠그고 attempt가 선점 때 값과 같고 아직 generating일 때만 저장한다(조건부 갱신).
-- 선점이 만료돼 다른 요청이 다시 선점했거나(attempt가 다름) 이미 ready이면 stale이다. 이때 아무것도 쓰지 않는다.
--
-- p_items: [{term_id, reason, question, answer, explanation, difficulty}, ...] 1~10개. 배열 순서가 문항 표시 순서(id 순)다.
-- reason은 viewed·favorited다(열람과 즐겨찾기가 겹치면 favorited, 6.2절). 한 용어에 문항 하나는 quiz_items_set_term_idx가 지킨다.
-- 반환: 'stored' | 'stale'
create function public.quiz_store_items(
  p_set_id bigint,
  p_attempt integer,
  p_items jsonb
)
returns text
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_item jsonb;
begin
  if p_set_id is null or p_attempt is null or p_items is null
     or jsonb_typeof(p_items) <> 'array'
     or jsonb_array_length(p_items) not between 1 and 10 then
    raise exception 'invalid quiz items arguments';
  end if;

  perform 1
    from public.quiz_sets q
   where q.id = p_set_id and q.attempt = p_attempt and q.status = 'generating'
     for update;
  if not found then
    return 'stale';
  end if;

  insert into public.quiz_set_terms (set_id, term_id, reason)
  select p_set_id, (e.item ->> 'term_id')::bigint, e.item ->> 'reason'
    from jsonb_array_elements(p_items) as e(item);

  -- 문항은 배열 순서대로 한 행씩 넣는다. INSERT ... SELECT ... ORDER BY의 행 순서는 id 부여 순서를 보장하지 않으므로,
  -- 반복문으로 id가 배열 순서를 따르게 한다(최대 10개).
  for v_item in
    select e.item from jsonb_array_elements(p_items) with ordinality as e(item, n) order by e.n
  loop
    insert into public.quiz_items (set_id, term_id, question, answer, explanation, difficulty)
    values (
      p_set_id,
      (v_item ->> 'term_id')::bigint,
      v_item ->> 'question',
      v_item ->> 'answer',
      v_item ->> 'explanation',
      v_item ->> 'difficulty'
    );
  end loop;

  update public.quiz_sets
     set status = 'ready', lease_expires_at = null
   where id = p_set_id;
  return 'stored';
end;
$$;

revoke execute on function public.quiz_store_items(bigint, integer, jsonb) from public, anon, authenticated;
grant execute on function public.quiz_store_items(bigint, integer, jsonb) to service_role;
