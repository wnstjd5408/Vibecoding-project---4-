-- 운영자 노트 수정·삭제 SQL 함수 (MEG-79, API spec v0.2 2.3 E17·E18, S1·S14, Q-N1)
-- 접근 모델은 앞 마이그레이션과 같다: FastAPI(service_role)만 호출한다.
-- 노트 쓰기와 AI 설명 무효화는 같은 트랜잭션이어야 해서 함수로 묶는다. 노트 작성(E16)은 한 표에 한 행을 넣을 뿐이라
-- 함수 없이 REST로 한다. 과목·출처·상위 노트는 PRD 반영 전까지 확정 대기라 이 함수들도 다루지 않는다.

-- ---------------------------------------------------------------------------
-- 1. 노트 수정·공개 전환 (E17)
-- ---------------------------------------------------------------------------
-- p_fields에는 바꿀 열만 담는다. 키가 있으면 그 값으로 바꾸고(null이면 비운다), 키가 없으면 그대로 둔다.
-- 허용 키: title, body_markdown, studied_on, study_minutes, importance, understanding, needs_review, memo,
-- is_published. API가 형식·범위를 먼저 검사하고 DB check는 마지막 방어선이다.
-- p_expected_revision이 null이 아니고 현재 값과 다르면 아무것도 바꾸지 않고 stale_revision을 돌려준다.
-- 행을 잠근 채로 비교하고 바꾸므로 같은 노트를 동시에 고쳐도 둘 다 같은 개정 번호를 보고 통과하지 못한다.
-- 개정 번호가 오르거나 공개 노트를 비공개로 바꾸면(S14) 그 노트를 문맥으로 쓴 공유 AI 설명을 같은 트랜잭션에서
-- 무효화한다. 비공개 노트를 다시 비공개로 두는 것은 무효화하지 않는다.
create function public.note_update(
  p_note_id bigint,
  p_fields jsonb,
  p_expected_revision integer
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_old public.notes;
  v_new public.notes;
begin
  select * into v_old from public.notes where id = p_note_id for update;
  if not found then
    return jsonb_build_object('status', 'not_found');
  end if;

  if p_expected_revision is not null and p_expected_revision <> v_old.revision then
    return jsonb_build_object('status', 'stale_revision');
  end if;

  update public.notes set
    title = case when p_fields ? 'title' then p_fields ->> 'title' else title end,
    body_markdown = case when p_fields ? 'body_markdown' then p_fields ->> 'body_markdown' else body_markdown end,
    studied_on = case when p_fields ? 'studied_on' then (p_fields ->> 'studied_on')::date else studied_on end,
    study_minutes = case when p_fields ? 'study_minutes' then (p_fields ->> 'study_minutes')::integer else study_minutes end,
    importance = case when p_fields ? 'importance' then p_fields ->> 'importance' else importance end,
    understanding = case when p_fields ? 'understanding' then (p_fields ->> 'understanding')::smallint else understanding end,
    needs_review = case when p_fields ? 'needs_review' then (p_fields ->> 'needs_review')::boolean else needs_review end,
    memo = case when p_fields ? 'memo' then p_fields ->> 'memo' else memo end,
    is_published = case when p_fields ? 'is_published' then (p_fields ->> 'is_published')::boolean else is_published end
  where id = p_note_id
  returning * into v_new;

  if v_new.revision <> v_old.revision or (v_old.is_published and not v_new.is_published) then
    perform public.ai_invalidate_explanations(p_note_id, null, null);
  end if;

  return jsonb_build_object(
    'status', 'ok', 'id', v_new.id, 'revision', v_new.revision, 'is_published', v_new.is_published
  );
end;
$$;

revoke execute on function public.note_update(bigint, jsonb, integer) from public, anon, authenticated;
grant execute on function public.note_update(bigint, jsonb, integer) to service_role;

-- ---------------------------------------------------------------------------
-- 2. 노트 삭제 (E18)
-- ---------------------------------------------------------------------------
-- 이미지별 Storage 삭제 작업(pending)을 넣고, 그 노트를 문맥으로 쓴 공유 AI 설명을 무효화한 뒤 노트를 지운다.
-- 노트 삭제 전에 무효화해야 ai_explanations.note_id가 null이 돼도 설명이 유효한 채로 남지 않는다.
-- note_subjects·note_sources·note_images는 연쇄 삭제되고, 자식 노트의 parent_note_id는 null이 된다.
-- 돌려주는 jobs는 INSERT RETURNING으로 얻은 이번 호출의 작업이다.
-- enqueue_note_image_delete_jobs와 같은 INSERT지만 작업 ID도 반환하므로 여기서 직접 수행한다.
create function public.note_delete(p_note_id bigint, p_bucket text)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_jobs jsonb;
begin
  perform 1 from public.notes where id = p_note_id for update;
  if not found then
    return jsonb_build_object('status', 'not_found');
  end if;

  with inserted as (
    insert into public.storage_delete_jobs (bucket, object_path)
    select p_bucket, ni.storage_path from public.note_images ni where ni.note_id = p_note_id
    returning id, object_path
  )
  select coalesce(jsonb_agg(jsonb_build_object('id', j.id, 'path', j.object_path) order by j.id), '[]'::jsonb)
    into v_jobs
    from inserted j;

  perform public.ai_invalidate_explanations(p_note_id, null, null);
  delete from public.notes where id = p_note_id;

  return jsonb_build_object('status', 'ok', 'jobs', v_jobs);
end;
$$;

revoke execute on function public.note_delete(bigint, text) from public, anon, authenticated;
grant execute on function public.note_delete(bigint, text) to service_role;
