-- 로컬 db reset 때만 실행된다. 과목 이름만 넣고 노트 본문은 넣지 않는다(AC-6).
insert into public.subjects (name) values
  ('네트워크'),
  ('AI'),
  ('프론트'),
  ('백엔드'),
  ('인프라'),
  ('모바일'),
  ('보안'),
  ('운영체제(OS)'),
  ('DB&Storage');
