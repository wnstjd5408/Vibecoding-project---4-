-- 노트와 과목 연결을 한 트랜잭션으로 저장한다. 재실행은 기존 노트를 바꾸지 않는다.
create function public.import_notion_note(
  p_notion_page_id uuid,
  p_title text,
  p_body_markdown text,
  p_studied_on date,
  p_subject_names text[]
) returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_note_id bigint;
  v_subject_id bigint;
  v_name text;
begin
  if p_notion_page_id is null then
    raise exception using errcode = '22023', message = 'page_id_required';
  end if;

  select id into v_note_id from public.notes
    where notion_page_id = p_notion_page_id::text;
  if found then
    return jsonb_build_object('id', v_note_id, 'created', false);
  end if;

  if p_subject_names is null or cardinality(p_subject_names) > 100
     or exists (select 1 from unnest(p_subject_names) as s(name)
                where name is null or char_length(name) not between 1 and 100) then
    raise exception using errcode = '22023', message = 'invalid_subject_names';
  end if;

  insert into public.notes (notion_page_id, title, body_markdown, studied_on, is_published, imported_at)
    values (p_notion_page_id::text, p_title, p_body_markdown, p_studied_on, false, now())
    on conflict (notion_page_id) do nothing
    returning id into v_note_id;
  if not found then
    select id into v_note_id from public.notes where notion_page_id = p_notion_page_id::text;
    if v_note_id is null then
      raise exception using errcode = '40001', message = 'retry_import';
    end if;
    return jsonb_build_object('id', v_note_id, 'created', false);
  end if;

  -- Stable ordering avoids opposite subject lock ordering across concurrent imports.
  for v_name in select distinct name from unnest(p_subject_names) as s(name) order by name loop
    insert into public.subjects (name) values (v_name) on conflict (name) do nothing;
    select id into v_subject_id from public.subjects where name = v_name;
    insert into public.note_subjects (note_id, subject_id) values (v_note_id, v_subject_id);
  end loop;
  return jsonb_build_object('id', v_note_id, 'created', true);
end;
$$;

revoke all on function public.import_notion_note(uuid, text, text, date, text[]) from public, anon, authenticated;
grant execute on function public.import_notion_note(uuid, text, text, date, text[]) to service_role;
