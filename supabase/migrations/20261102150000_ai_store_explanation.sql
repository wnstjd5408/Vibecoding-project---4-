-- E09 AI 설명 저장 (MEG-87, API spec v0.2 5.5절 11~12단계)
--
-- 노트가 아직 공개이고 revision이 같은지 다시 확인한 뒤, 용어(terms, source = 'ai')와 공유 설명(ai_explanations)을
-- 한 트랜잭션으로 넣는다. 노트 행을 for share로 잠가서, 확인 뒤에 노트가 바뀌어 낡은 설명이 공유 캐시에 남는 일을
-- 막는다(노트 쓰기 함수는 같은 행을 for update로 잡는다).
--
-- outcome:
--   stored   설명을 저장했다(새 용어이거나 설명이 없던 용어).
--   existing 같은 용어를 동시에 만든 다른 요청이 먼저 저장했다. 내 설명은 버리고 저장된 설명을 돌려준다(12단계).
--   glossary 그 사이 사전에 등록된 용어다. 사전이 AI보다 우선하므로 저장하지 않는다(D-020).
--   one_off  노트가 비공개가 됐거나 revision이 달라졌다. 저장하지 않고 1회용으로 돌려준다(11단계).
-- 반환 열 이름에 out_ 접두사를 붙인 것은 ON CONFLICT·WHERE의 열 이름과 겹쳐 모호해지지 않게 하려는 것이다.
create function public.ai_store_explanation(
  p_note_id bigint,
  p_note_revision integer,
  p_term_key text,
  p_term_label text,
  p_sentence_hash text,
  p_body text,
  p_model text,
  p_prompt_version text
)
returns table (
  out_outcome text,
  out_term_id bigint,
  out_explanation_id bigint,
  out_body text,
  out_review_status text
)
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_is_published boolean;
  v_revision integer;
  v_term_id bigint;
  v_explanation_id bigint;
begin
  if p_note_id is null or p_note_revision is null
     or p_term_key is null or char_length(p_term_key) not between 1 and 200
     or p_term_label is null or char_length(p_term_label) not between 1 and 200
     or p_body is null or btrim(p_body) = ''
     or p_model is null or p_prompt_version is null then
    raise exception 'invalid ai explanation arguments';
  end if;

  select n.is_published, n.revision
    into v_is_published, v_revision
    from public.notes n
   where n.id = p_note_id
     for share;

  if not found or not v_is_published or v_revision <> p_note_revision then
    out_outcome := 'one_off';
    return next;
    return;
  end if;

  select t.id into v_term_id from public.terms t where t.key = p_term_key;
  if v_term_id is null then
    insert into public.terms (key, label, source)
    values (p_term_key, p_term_label, 'ai')
    on conflict (key) do nothing
    returning id into v_term_id;
    if v_term_id is null then
      -- 같은 용어를 동시에 만든 요청이 먼저 넣었다. 그 행을 다시 읽어 이어간다.
      select t.id into v_term_id from public.terms t where t.key = p_term_key;
    end if;
  end if;

  if exists (select 1 from public.glossary_entries g where g.term_id = v_term_id) then
    out_outcome := 'glossary';
    out_term_id := v_term_id;
    return next;
    return;
  end if;

  insert into public.ai_explanations
    (term_id, term_key_snapshot, note_id, note_revision, sentence_hash, body, model, prompt_version)
  values
    (v_term_id, p_term_key, p_note_id, p_note_revision, p_sentence_hash, p_body, p_model, p_prompt_version)
  on conflict (term_id) where invalidated_at is null and term_id is not null do nothing
  returning id into v_explanation_id;

  out_term_id := v_term_id;
  if v_explanation_id is null then
    -- 활성 설명이 이미 있다. 그 설명을 돌려준다.
    select e.id, e.body, e.review_status
      into v_explanation_id, out_body, out_review_status
      from public.ai_explanations e
     where e.term_id = v_term_id
       and e.invalidated_at is null;
    out_outcome := 'existing';
    out_explanation_id := v_explanation_id;
  else
    out_outcome := 'stored';
    out_explanation_id := v_explanation_id;
    out_body := p_body;
    out_review_status := 'pending';
  end if;
  return next;
end;
$$;

revoke execute on function public.ai_store_explanation(bigint, integer, text, text, text, text, text, text)
  from public, anon, authenticated;
grant execute on function public.ai_store_explanation(bigint, integer, text, text, text, text, text, text)
  to service_role;
