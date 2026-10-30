-- MEG-132: synthetic local fixture, invoked only by local_backend.py.
-- Reserved identity range 132001..132099; never run on a shared/remote database.
begin;

-- Fail rather than overwrite a non-fixture row occupying the reserved range.
do $$ begin
  if exists (select 1 from public.terms where id between 132001 and 132099 and key not like 'fixture %')
     or exists (select 1 from public.notes where id = 132001 and title <> '합성 개발 노트') then
    raise exception 'Fixture identity collision';
  end if;
end $$;

delete from public.reports where user_id in (
  '13200000-0000-4000-8000-000000000001', '13200000-0000-4000-8000-000000000002',
  '13200000-0000-4000-8000-000000000003', '13200000-0000-4000-8000-000000000004');
delete from public.quiz_sets where user_id in (
  '13200000-0000-4000-8000-000000000002', '13200000-0000-4000-8000-000000000003');
delete from public.ai_explanations where id between 132001 and 132099;
delete from public.terms where id between 132001 and 132099;
delete from public.notes where id = 132001;

insert into public.profiles (user_id, role, is_active, display_name) values
 ('13200000-0000-4000-8000-000000000001', 'operator', true, '합성 운영자'),
 ('13200000-0000-4000-8000-000000000002', 'member', true, '합성 사용자 A'),
 ('13200000-0000-4000-8000-000000000003', 'member', true, '합성 사용자 B'),
 ('13200000-0000-4000-8000-000000000004', 'member', false, '합성 비활성 사용자')
on conflict (user_id) do update set role = excluded.role, is_active = excluded.is_active,
 display_name = excluded.display_name;

insert into public.notes (id, title, body_markdown, is_published)
overriding system value values (132001, '합성 개발 노트', '테스트 전용 문장입니다. 실제 학습 자료가 아닙니다.', true);
insert into public.terms (id, key, label, source) overriding system value values
 (132001, 'fixture alpha', '합성 용어 A', 'ai'),
 (132002, 'fixture beta', '합성 용어 B', 'ai'),
 (132003, 'fixture gamma', '합성 용어 C', 'ai'),
 (132004, 'fixture old', '합성 무효 용어', 'ai'),
 (132005, 'fixture glossary', '합성 사전 용어', 'glossary');
insert into public.glossary_entries (term_id, body_markdown)
values (132005, '합성 사전 설명');

insert into public.ai_explanations
 (id, term_id, term_key_snapshot, note_id, note_revision, body, model, prompt_version, invalidated_at, created_at)
overriding system value values
 (132001, 132001, 'fixture alpha', 132001, 1, '합성 설명 A', 'synthetic-no-call', 'fixture-v1', null, '2026-10-29T00:00:00Z'),
 (132002, 132002, 'fixture beta', 132001, 1, '합성 설명 B', 'synthetic-no-call', 'fixture-v1', null, '2026-10-29T00:00:00Z'),
 (132003, 132003, 'fixture gamma', 132001, 1, '합성 설명 C', 'synthetic-no-call', 'fixture-v1', null, '2026-10-29T00:00:00Z'),
 (132004, 132004, 'fixture old', 132001, 1, '합성 무효 설명', 'synthetic-no-call', 'fixture-v1', '2026-10-30T00:00:00Z', '2026-10-29T00:00:00Z');

insert into public.favorites (user_id, term_id, created_at) values
 ('13200000-0000-4000-8000-000000000002',132001,'2026-10-29T15:00:00Z'),
 ('13200000-0000-4000-8000-000000000003',132002,'2026-10-29T15:00:00Z');
insert into public.favorite_events (user_id, term_id, study_date) values
 ('13200000-0000-4000-8000-000000000002',132001,'2026-10-29'),
 ('13200000-0000-4000-8000-000000000002',132001,'2026-10-30'),
 ('13200000-0000-4000-8000-000000000002',132003,'2026-10-30'),
 ('13200000-0000-4000-8000-000000000003',132002,'2026-10-30');

insert into public.quiz_sets (id, user_id, quiz_date, source_date, status)
overriding system value values
 (132001,'13200000-0000-4000-8000-000000000002','2026-10-30','2026-10-29','ready'),
 (132002,'13200000-0000-4000-8000-000000000003','2026-10-30','2026-10-29','ready');
insert into public.quiz_set_terms (set_id, term_id, reason) values
 (132001,132001,'favorited'), (132002,132002,'favorited');
insert into public.quiz_items (id, set_id, term_id, question, answer, explanation, difficulty)
overriding system value values
 (132001,132001,132001,'합성 질문 A','합성 답 A','합성 해설 A','하'),
 (132002,132002,132002,'합성 질문 B','합성 답 B','합성 해설 B','하');

insert into public.reports (id, user_id, ai_explanation_id, quiz_item_id, body, status, created_at, resolved_at)
overriding system value values
 (132001,'13200000-0000-4000-8000-000000000002',132001,null,'생략값 시험','open','2026-10-30T00:00:00Z',null),
 (132002,'13200000-0000-4000-8000-000000000002',132002,null,'false 시험','open','2026-10-30T00:00:00Z',null),
 (132003,'13200000-0000-4000-8000-000000000002',132003,null,'true 시험','open','2026-10-30T00:00:00Z',null),
 (132004,'13200000-0000-4000-8000-000000000002',null,132001,'퀴즈 신고','open','2026-10-30T00:00:00Z',null),
 (132005,'13200000-0000-4000-8000-000000000003',null,132002,'다른 사용자 퀴즈 신고','open','2026-10-30T00:00:00Z',null),
 (132006,'13200000-0000-4000-8000-000000000003',132004,null,'처리된 신고','resolved','2026-10-29T00:00:00Z','2026-10-30T00:00:00Z');
commit;
