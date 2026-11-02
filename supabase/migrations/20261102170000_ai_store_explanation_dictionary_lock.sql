-- MEG-81 리뷰 수정: E09 AI 설명 저장(ai_store_explanation)과 E20 사전 등록(glossary_upsert_entry)의 경합을 막는다.
--
-- 문제: E20은 terms 행을 갱신(FOR NO KEY UPDATE)하고, E09는 ai_explanations를 넣을 때 외래 키 확인으로 terms 행에
-- FOR KEY SHARE만 건다. 두 잠금은 서로 막지 않는다. 게다가 E09는 사전 존재(glossary_entries)를 잠금 없이 확인하므로
-- 커밋 전인 E20의 사전 행을 못 본다. 그래서 E20 커밋 뒤에 source = 'glossary'인 용어에 유효한 AI 설명이 남을 수 있다.
--
-- 규약: 같은 용어에 대해 두 함수가 terms 행 잠금을 먼저 잡고, 그 잠금을 얻은 뒤에 사전 존재를 확인한다.
--   E20: terms 행을 FOR NO KEY UPDATE로 잡는다(upsert의 갱신). 그 뒤 AI 설명을 무효화한다.
--   E09: terms 행을 FOR SHARE로 잡는다. FOR SHARE는 FOR NO KEY UPDATE와 서로 막는다.
-- 그러면 E09는 E20이 끝나길 기다린 뒤 사전 용어임을 보고 저장하지 않고(outcome = 'glossary'), E20은 E09가 끝나길
-- 기다린 뒤 방금 저장된 설명까지 무효화한다. 잠금 순서는 terms → glossary_entries → ai_explanations로 E20·E21·E22와 같다.
--
-- 이 파일은 20261102150000_ai_store_explanation.sql(MEG-87, 병합됨)의 함수를 create or replace로 보강한다.
-- 시그니처·반환 열·권한은 그대로이고 바뀐 곳은 아래 "MEG-81" 표시 부분뿐이다.
create or replace function public.ai_store_explanation(
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

  -- MEG-81: 사전 존재를 확인하기 전에 용어 행을 FOR SHARE로 잠근다. 커밋 전인 사전 등록(E20)이 있으면 그것이 끝날
  -- 때까지 여기서 기다리고, 다음 문장은 새 스냅샷으로 E20이 커밋한 사전 행을 본다. 잠금은 이 함수가 속한 트랜잭션이
  -- 끝날 때까지 유지되므로, 아래에서 설명을 넣는 동안 E20이 끼어들 수 없고 E20은 이 설명이 커밋된 뒤 무효화한다.
  perform 1 from public.terms t where t.id = v_term_id for share;

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
