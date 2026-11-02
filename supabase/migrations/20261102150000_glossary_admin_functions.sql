-- MEG-81 운영자 사전 쓰기(E20~E23)의 원자 작업 SQL 함수와 사전 이미지 공개 버킷.
-- API spec v0.2 2.3·2.4·1.4.4, Q-N1(원자 작업만 SQL 함수, service_role만 EXECUTE), Q-N4(E21은 사전 설명·이미지만 삭제).
-- 함수는 모두 security invoker이고 search_path를 비운다. FastAPI가 secret key(service_role)로만 부른다.

-- ---------------------------------------------------------------------------
-- 1. E20 사전 등록·갱신
-- ---------------------------------------------------------------------------
-- key는 앱이 label에서 정규화해 넘긴다(terms_key_normalized_check가 마지막 방어선이다).
-- 같은 key의 terms가 있으면 label을 새 값으로 바꾸고 source를 'glossary'로 바꾼다(사전이 AI보다 우선, D-020).
-- 그 용어의 유효한 AI 설명은 같은 트랜잭션에서 무효화한다. 이미 사전 용어였어도 부르며, 무효화할 행이 없으면 0건이다.
-- 돌려주는 값: {"id", "key", "label", "created"}. created는 사전 설명(glossary_entries)이 새로 생겼는지다(201/200).
create function public.glossary_upsert_entry(
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
  insert into public.terms (key, label, source)
  values (p_key, p_label, 'glossary')
  on conflict (key) do update
    set label = excluded.label,
        source = 'glossary'
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

-- ---------------------------------------------------------------------------
-- 2. E21 사전 설명·이미지 삭제 (Q-N4)
-- ---------------------------------------------------------------------------
-- glossary_images를 지우며 이미지마다 storage_delete_jobs(pending)를 넣고, glossary_entries를 지우고,
-- terms.source를 'ai'로 바꾼다. terms 행과 favorites·term_views·favorite_events·quiz_set_terms는 건드리지 않는다.
-- 사전 용어가 아니면(glossary_entries 행 없음) 아무것도 바꾸지 않고 null을 돌려준다(404).
-- 돌려주는 값: {"jobs": [{"job_id", "object_path"}, ...]}. 앱이 트랜잭션 뒤에 객체 삭제를 시도한다.
create function public.glossary_delete_entry(p_term_id bigint, p_bucket text)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_jobs jsonb;
begin
  -- 같은 용어에 이미지를 붙이는 요청(glossary_add_image)과 순서를 정한다.
  perform 1 from public.glossary_entries where term_id = p_term_id for update;
  if not found then
    return null;
  end if;

  with deleted as (
    delete from public.glossary_images
    where term_id = p_term_id
    returning storage_path
  ), jobs as (
    insert into public.storage_delete_jobs (bucket, object_path)
    select p_bucket, storage_path from deleted
    returning id, object_path
  )
  select coalesce(jsonb_agg(jsonb_build_object('job_id', id, 'object_path', object_path) order by id), '[]'::jsonb)
    into v_jobs
  from jobs;

  delete from public.glossary_entries where term_id = p_term_id;
  update public.terms set source = 'ai' where id = p_term_id;

  return jsonb_build_object('jobs', v_jobs);
end;
$$;

-- ---------------------------------------------------------------------------
-- 3. E22 이미지 행 등록 (업로드 성공 뒤)
-- ---------------------------------------------------------------------------
-- 순서(1.4.4): 앱이 storage_delete_jobs(pending)를 먼저 넣고 → Storage에 올리고 → 이 함수가 glossary_images를 넣고
-- 같은 트랜잭션에서 그 job을 지운다. 그 사이 사전 설명이 지워졌으면 null을 돌려주고 job은 남긴다(객체는 지울 대상).
create function public.glossary_add_image(
  p_term_id bigint,
  p_storage_path text,
  p_alt text,
  p_job_id bigint
)
returns bigint
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_image_id bigint;
begin
  -- E21과 동시에 오면 둘 중 하나가 먼저 끝난다. 사전 설명이 없는 용어에 이미지 행이 남지 않게 한다.
  perform 1 from public.glossary_entries where term_id = p_term_id for share;
  if not found then
    return null;
  end if;

  insert into public.glossary_images (term_id, storage_path, alt)
  values (p_term_id, p_storage_path, p_alt)
  returning id into v_image_id;

  delete from public.storage_delete_jobs
  where id = p_job_id and status = 'pending' and object_path = p_storage_path;

  return v_image_id;
end;
$$;

-- ---------------------------------------------------------------------------
-- 4. E23 이미지 한 장 삭제
-- ---------------------------------------------------------------------------
-- glossary_images 행을 지우고 같은 트랜잭션에서 storage_delete_jobs(pending)를 넣는다. 객체 삭제는 앱이 뒤에 시도한다.
-- 그 용어의 이미지가 아니면 null(404). 돌려주는 값: {"job_id", "object_path"}.
create function public.glossary_delete_image(p_term_id bigint, p_image_id bigint, p_bucket text)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_path text;
  v_job_id bigint;
begin
  delete from public.glossary_images
  where id = p_image_id and term_id = p_term_id
  returning storage_path into v_path;
  if not found then
    return null;
  end if;

  insert into public.storage_delete_jobs (bucket, object_path)
  values (p_bucket, v_path)
  returning id into v_job_id;

  return jsonb_build_object('job_id', v_job_id, 'object_path', v_path);
end;
$$;

revoke execute on function public.glossary_upsert_entry(text, text, text, uuid) from public, anon, authenticated;
grant execute on function public.glossary_upsert_entry(text, text, text, uuid) to service_role;
revoke execute on function public.glossary_delete_entry(bigint, text) from public, anon, authenticated;
grant execute on function public.glossary_delete_entry(bigint, text) to service_role;
revoke execute on function public.glossary_add_image(bigint, text, text, bigint) from public, anon, authenticated;
grant execute on function public.glossary_add_image(bigint, text, text, bigint) to service_role;
revoke execute on function public.glossary_delete_image(bigint, bigint, text) from public, anon, authenticated;
grant execute on function public.glossary_delete_image(bigint, bigint, text) to service_role;

-- ---------------------------------------------------------------------------
-- 5. 사전 이미지 공개 읽기 버킷 (기술 검토 Q7 결정 (a), 2026-11-02)
-- ---------------------------------------------------------------------------
-- 버킷 설정은 마이그레이션으로 만든다(docs/architecture.md 7절). 앱의 GLOSSARY_IMAGE_BUCKET은 이 이름이다.
-- 앱이 올리기 전에 4MB·형식을 검사하고 다시 인코딩한다. 버킷 제한은 재인코딩 결과의 상한(10MB)과 형식만 막는 마지막 방어선이다.
-- Storage가 없는 일회용 PostgreSQL(SQL 함수 시험)에서는 건너뛴다.
do $$
begin
  if to_regclass('storage.buckets') is not null then
    insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
    values ('glossary-images', 'glossary-images', true, 10485760, array['image/png', 'image/jpeg', 'image/webp'])
    on conflict (id) do update
      set public = excluded.public,
          file_size_limit = excluded.file_size_limit,
          allowed_mime_types = excluded.allowed_mime_types;
  end if;
end;
$$;
