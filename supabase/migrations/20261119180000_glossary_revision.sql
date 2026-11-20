-- MEG-249(CS Agent T4a): 사전 항목의 개정 번호 terms.glossary_revision을 추가한다.
-- 근거: 내부 위키 우선 RAG 설계 v0.3(MEG-163) 3.2절 '개정' 행, W1(위키 = 사전 항목) 결정(사용자 2026-11-19).
-- 위키 출처(사전 항목)를 인용할 때 ai_turn_sources.cited_revision에 이 값을 적는다(T4c).
--
-- 번호를 glossary_entries가 아니라 terms에 두는 이유: E21(glossary_delete_entry)은 glossary_entries 행을 지우고
-- terms 행은 남긴다. glossary_entries에 두면 같은 key로 다시 등록할 때 1부터 다시 시작해, 같은 번호가 다른 본문을 가리킨다.
--
-- 추가만 한다. 기존 행의 값은 바꾸지 않는다. 그래서 이 마이그레이션 전에 등록된 사전 항목은 0이고,
-- 다음 저장(E20)부터 1씩 오른다. 처음 등록하는 항목은 1부터 시작한다.

-- ---------------------------------------------------------------------------
-- 1. 열 추가
-- ---------------------------------------------------------------------------
-- 상수 기본값이 있는 not null 열 추가라 테이블을 다시 쓰지 않는다. 같은 문장의 check 제약은 기존 행을 한 번 읽어
-- 확인하므로 그동안 terms에 배타 잠금이 걸린다. 지금 terms는 작아 짧게 끝난다.
alter table public.terms
  add column glossary_revision integer not null default 0
    constraint terms_glossary_revision_check check (glossary_revision >= 0);

comment on column public.terms.glossary_revision is
  '사전 저장(E20 glossary_upsert_entry)마다 1씩 오르는 개정 번호. 사전 삭제(E21) 뒤에도 남아 재등록 시 이어서 오른다. 0은 저장 기록이 없거나 이 열을 추가하기 전에 저장된 항목이다.';

-- ---------------------------------------------------------------------------
-- 2. E20 사전 등록·갱신: 저장할 때마다 개정 번호를 올린다
-- ---------------------------------------------------------------------------
-- 20261102160000_glossary_admin_functions.sql(MEG-81, 병합됨)의 함수를 create or replace로 바꾼다.
-- 시그니처, 반환 값({"id", "key", "label", "created"}), 권한, 잠금 순서(terms → glossary_entries)는 그대로다.
-- 바뀐 곳은 "MEG-249" 표시 부분뿐이다.
-- 같은 key를 동시에 저장해도 on conflict 갱신이 terms 행을 잠그므로 저장 하나에 번호 하나씩 오른다.
create or replace function public.glossary_upsert_entry(
  p_key text,
  p_label text,
  p_body_markdown text,
  p_updated_by uuid
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_term_id bigint;
  v_created boolean;
begin
  -- MEG-249: 새 용어는 1, 이미 있는 용어(AI 용어였거나 사전에서 지운 용어 포함)는 지금 번호 + 1이다.
  insert into public.terms as t (key, label, source, glossary_revision)
  values (p_key, p_label, 'glossary', 1)
  on conflict (key) do update
    set label = excluded.label,
        source = 'glossary',
        glossary_revision = t.glossary_revision + 1
  returning id into v_term_id;

  insert into public.glossary_entries (term_id, body_markdown, updated_by)
  values (v_term_id, p_body_markdown, p_updated_by)
  on conflict on constraint glossary_entries_pkey do update
    set body_markdown = excluded.body_markdown,
        updated_by = excluded.updated_by
  -- 새로 넣은 행은 xmax가 0이다. 충돌로 갱신한 행은 0이 아니다.
  returning (xmax = 0) into v_created;

  perform public.ai_invalidate_explanations(null, v_term_id, null);

  return (
    select jsonb_build_object('id', t.id, 'key', t.key, 'label', t.label, 'created', v_created)
    from public.terms t
    where t.id = v_term_id
  );
end;
$$;

-- create or replace는 권한을 유지한다. 그래도 같은 파일에서 확인할 수 있게 다시 적는다.
revoke execute on function public.glossary_upsert_entry(text, text, text, uuid) from public, anon, authenticated;
grant execute on function public.glossary_upsert_entry(text, text, text, uuid) to service_role;
