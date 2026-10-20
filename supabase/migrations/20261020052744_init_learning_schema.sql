-- CS 학습 도구 첫 스키마 (PRD 초안 v0.1 5절)
-- 접근 모델: 브라우저는 Supabase에 직접 붙지 않고 FastAPI만 호출한다.
-- FastAPI는 secret key(service_role)로 접근하므로 anon/authenticated에는 아무 권한도 주지 않는다.

-- 과목 (Notion "과목" 다중 선택 값)
create table public.subjects (
  id bigint generated always as identity primary key,
  name text not null unique check (char_length(name) between 1 and 100),
  created_at timestamptz not null default now()
);

-- 학습 노트 (Notion "공부 기록" 페이지 1개 = 1행)
create table public.notes (
  id bigint generated always as identity primary key,
  -- 앱에서 직접 만든 노트는 null. 가져오기 재실행 시 중복을 막는다.
  notion_page_id text unique,
  title text not null check (char_length(title) between 1 and 300),
  body_markdown text not null default '',
  studied_on date,
  study_minutes integer check (study_minutes >= 0),
  importance text check (importance in ('상', '중', '하')),
  understanding smallint check (understanding between 1 and 5),
  needs_review boolean not null default false,
  memo text,
  parent_note_id bigint references public.notes (id) on delete set null,
  imported_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index notes_parent_note_id_idx on public.notes (parent_note_id);

-- 노트-과목 연결 (다대다)
create table public.note_subjects (
  note_id bigint not null references public.notes (id) on delete cascade,
  subject_id bigint not null references public.subjects (id) on delete restrict,
  primary key (note_id, subject_id)
);

create index note_subjects_subject_id_idx on public.note_subjects (subject_id);

-- 노트의 출처 링크
create table public.note_sources (
  id bigint generated always as identity primary key,
  note_id bigint not null references public.notes (id) on delete cascade,
  url text not null check (url ~* '^https?://'),
  label text,
  created_at timestamptz not null default now(),
  unique (note_id, url)
);

-- 보안: RLS를 켜고 정책은 만들지 않는다. anon/authenticated는 행을 볼 수 없다.
alter table public.subjects enable row level security;
alter table public.notes enable row level security;
alter table public.note_subjects enable row level security;
alter table public.note_sources enable row level security;

-- Data API 기본 권한을 회수하고 백엔드(service_role)에만 필요한 권한을 준다.
revoke all on table public.subjects, public.notes, public.note_subjects, public.note_sources
  from anon, authenticated;
grant select, insert, update, delete
  on table public.subjects, public.notes, public.note_subjects, public.note_sources
  to service_role;
grant usage on all sequences in schema public to service_role;

-- 앞으로 public에 만드는 객체도 anon/authenticated에 자동 노출되지 않게 한다.
alter default privileges for role postgres in schema public
  revoke all on tables from anon, authenticated;
alter default privileges for role postgres in schema public
  revoke all on sequences from anon, authenticated;
alter default privileges for role postgres in schema public
  revoke all on functions from anon, authenticated, public;
