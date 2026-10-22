-- CS 학습 노트 스키마 확장 (MEG-35 T1, MEG-38 기술 검토 문서 4절 기준)
-- 접근 모델은 첫 마이그레이션과 같다: 브라우저는 FastAPI만 호출하고 FastAPI(service_role)만 DB에 접근한다.
-- 새 표 모두 RLS를 켜고 정책을 만들지 않으며 anon/authenticated 권한을 주지 않는다.

-- ---------------------------------------------------------------------------
-- notes: 공개 여부와 개정 번호
-- ---------------------------------------------------------------------------
alter table public.notes
  -- 비로그인·일반 사용자 API는 공개 노트만 돌려준다. 가져온 노트는 비공개로 시작한다(결정 2).
  add column is_published boolean not null default false,
  -- 제목·본문을 고칠 때 트리거로 1 올린다. 공유 AI 설명 무효화에 쓴다.
  add column revision integer not null default 1 check (revision >= 1);

create function public.bump_note_revision()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if new.title is distinct from old.title
     or new.body_markdown is distinct from old.body_markdown then
    new.revision := old.revision + 1;
  end if;
  return new;
end;
$$;

revoke execute on function public.bump_note_revision() from public, anon, authenticated;
grant execute on function public.bump_note_revision() to service_role;

create trigger notes_bump_revision
  before update on public.notes
  for each row execute function public.bump_note_revision();

-- ---------------------------------------------------------------------------
-- 사용자 프로필 (계정은 Supabase Auth, 역할·활성 여부의 원본은 이 표)
-- ---------------------------------------------------------------------------
create table public.profiles (
  user_id uuid primary key references auth.users (id) on delete cascade,
  role text not null check (role in ('operator', 'member')),
  is_active boolean not null default true,
  display_name text check (display_name is null or char_length(display_name) between 1 and 100)
);

-- ---------------------------------------------------------------------------
-- 용어 사전
-- ---------------------------------------------------------------------------
create table public.terms (
  id bigint generated always as identity primary key,
  -- 정규화한 용어. 사전 용어와 AI로 설명한 용어를 한 표에서 관리한다.
  key text not null unique check (char_length(key) between 1 and 200),
  label text not null check (char_length(label) between 1 and 200),
  source text not null check (source in ('glossary', 'ai'))
);

create table public.glossary_entries (
  term_id bigint primary key references public.terms (id) on delete cascade,
  body_markdown text not null default '',
  -- 작성자 계정을 지워도 사전 설명은 남긴다.
  updated_by uuid references public.profiles (user_id) on delete set null
);

create index glossary_entries_updated_by_idx on public.glossary_entries (updated_by);

create table public.glossary_images (
  id bigint generated always as identity primary key,
  term_id bigint not null references public.terms (id) on delete cascade,
  storage_path text not null,
  alt text
);

create index glossary_images_term_id_idx on public.glossary_images (term_id);

-- ---------------------------------------------------------------------------
-- AI 설명 공유 캐시 (용어 단위로 모든 사용자가 공유, 행은 지우지 않고 무효화한다)
-- ---------------------------------------------------------------------------
create table public.ai_explanations (
  id bigint generated always as identity primary key,
  -- 용어를 지워도 설명과 그에 대한 신고는 남긴다(결정 8). 삭제 당시 key는 snapshot에 보관한다.
  term_id bigint references public.terms (id) on delete set null,
  term_key_snapshot text not null,
  -- 생성 당시 문맥. 노트를 지워도 설명은 남긴다(애플리케이션이 같은 트랜잭션에서 무효화한다).
  note_id bigint references public.notes (id) on delete set null,
  note_revision integer,
  sentence_hash text,
  body text not null,
  model text not null,
  prompt_version text not null,
  -- 무효화는 review_status가 아니라 invalidated_at으로만 나타낸다.
  review_status text not null default 'pending'
    check (review_status in ('pending', 'approved')),
  invalidated_at timestamptz,
  created_at timestamptz not null default now(),
  -- 용어 삭제 API는 설명을 먼저 무효화한 뒤 용어를 지운다. 순서가 바뀐 삭제는 실패해 유효한 설명이 고아로 남지 않는다.
  check (term_id is not null or invalidated_at is not null)
);

-- 무효화되지 않은 설명은 용어당 하나다.
create unique index ai_explanations_active_term_idx
  on public.ai_explanations (term_id)
  where invalidated_at is null and term_id is not null;

create index ai_explanations_note_id_idx on public.ai_explanations (note_id);

-- ---------------------------------------------------------------------------
-- 열람·즐겨찾기
-- ---------------------------------------------------------------------------
create table public.term_views (
  user_id uuid not null references public.profiles (user_id) on delete cascade,
  term_id bigint not null references public.terms (id) on delete cascade,
  -- KST 날짜
  study_date date not null,
  primary key (user_id, term_id, study_date)
);

create index term_views_term_id_idx on public.term_views (term_id);

create table public.favorites (
  user_id uuid not null references public.profiles (user_id) on delete cascade,
  term_id bigint not null references public.terms (id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (user_id, term_id)
);

create index favorites_term_id_idx on public.favorites (term_id);

-- 즐겨찾기를 추가할 때 그날 날짜로 한 행을 넣고 해제해도 지우지 않는다(결정 5).
create table public.favorite_events (
  user_id uuid not null references public.profiles (user_id) on delete cascade,
  term_id bigint not null references public.terms (id) on delete cascade,
  -- KST 날짜
  study_date date not null,
  primary key (user_id, term_id, study_date)
);

create index favorite_events_term_id_idx on public.favorite_events (term_id);

-- ---------------------------------------------------------------------------
-- 다음 날 퀴즈
-- ---------------------------------------------------------------------------
create table public.quiz_sets (
  id bigint generated always as identity primary key,
  user_id uuid not null references public.profiles (user_id) on delete cascade,
  -- KST 날짜. 하루에 한 번만 만든다.
  quiz_date date not null,
  source_date date not null,
  -- 퀴즈 대상이 없으면 행을 만들지 않으므로 대기 상태는 두지 않는다.
  status text not null default 'generating'
    check (status in ('generating', 'ready', 'failed')),
  -- 생성 작업 선점 만료 시각과 시도 횟수
  lease_expires_at timestamptz,
  attempt integer not null default 0 check (attempt >= 0),
  unique (user_id, quiz_date),
  check (quiz_date = source_date + 1)
);

-- 퀴즈 생성 시점의 후보 용어 스냅샷. 용어를 지우면 후보 기록도 지운다(결정 4).
create table public.quiz_set_terms (
  set_id bigint not null references public.quiz_sets (id) on delete cascade,
  term_id bigint not null references public.terms (id) on delete cascade,
  reason text not null check (reason in ('viewed', 'favorited')),
  primary key (set_id, term_id)
);

create index quiz_set_terms_term_id_idx on public.quiz_set_terms (term_id);

create table public.quiz_items (
  id bigint generated always as identity primary key,
  set_id bigint not null references public.quiz_sets (id) on delete cascade,
  -- 용어를 지워도 이미 낸 문항은 남기고 연결만 끊는다.
  term_id bigint references public.terms (id) on delete set null,
  question text not null,
  answer text not null,
  -- 문항을 만들 때 쓴 근거의 스냅샷
  explanation text not null,
  difficulty text not null check (difficulty in ('상', '중', '하'))
);

create index quiz_items_set_id_idx on public.quiz_items (set_id);
create index quiz_items_term_id_idx on public.quiz_items (term_id);

create table public.quiz_answers (
  item_id bigint primary key references public.quiz_items (id) on delete cascade,
  user_answer text not null,
  answered_at timestamptz not null default now()
);

-- 꼬리 질문은 문항당 최대 2개다. 슬롯을 먼저 넣어 예약한 뒤 AI를 부르므로 질문·답변은 비어 있을 수 있다.
create table public.quiz_followups (
  item_id bigint not null references public.quiz_items (id) on delete cascade,
  seq smallint not null check (seq in (1, 2)),
  question text,
  user_answer text,
  primary key (item_id, seq)
);

-- ---------------------------------------------------------------------------
-- 틀림 신고 (AI 설명과 퀴즈 문항 중 정확히 하나를 가리킨다)
-- ---------------------------------------------------------------------------
create table public.reports (
  id bigint generated always as identity primary key,
  user_id uuid not null references public.profiles (user_id) on delete cascade,
  -- 신고가 걸린 AI 설명은 지우지 않는다. 퀴즈 문항은 사용자 삭제 때 신고와 함께 지운다(결정 6·8).
  ai_explanation_id bigint references public.ai_explanations (id) on delete restrict,
  quiz_item_id bigint references public.quiz_items (id) on delete cascade,
  body text not null default '',
  status text not null default 'open' check (status in ('open', 'resolved')),
  check ((ai_explanation_id is not null) <> (quiz_item_id is not null))
);

create index reports_user_id_idx on public.reports (user_id);
create index reports_ai_explanation_id_idx on public.reports (ai_explanation_id);
create index reports_quiz_item_id_idx on public.reports (quiz_item_id);

-- ---------------------------------------------------------------------------
-- AI 비용 예약 원장 (사용자를 지워도 비용 기록은 익명으로 남긴다, 결정 6)
-- ---------------------------------------------------------------------------
create table public.ai_usage_ledger (
  id bigint generated always as identity primary key,
  user_id uuid references public.profiles (user_id) on delete set null,
  kind text not null check (kind in ('explain', 'quiz', 'followup')),
  -- 시도마다 {논리 요청 id}:{attempt_no}로 만든다.
  idempotency_key text not null unique,
  reserved_usd numeric(12, 6) not null check (reserved_usd >= 0),
  actual_usd numeric(12, 6) check (actual_usd >= 0),
  input_tokens integer check (input_tokens >= 0),
  output_tokens integer check (output_tokens >= 0),
  attempt_no integer not null default 1 check (attempt_no >= 1),
  -- usage: 응답의 실제 사용량으로 정산. reserved_fallback: 시간 초과 등으로 응답이 없어 예약액 그대로 정산.
  settle_basis text check (settle_basis in ('usage', 'reserved_fallback')),
  settled_at timestamptz,
  status text not null default 'reserved' check (status in ('reserved', 'settled', 'released')),
  -- KST 날짜
  kst_date date not null,
  created_at timestamptz not null default now(),
  check (
    status <> 'settled'
    or (actual_usd is not null and settled_at is not null and settle_basis is not null)
  ),
  -- 토큰 수는 실제 사용량으로 정산할 때만 반드시 있다.
  check (
    settle_basis is distinct from 'usage'
    or (input_tokens is not null and output_tokens is not null)
  )
);

create index ai_usage_ledger_user_id_idx on public.ai_usage_ledger (user_id);
create index ai_usage_ledger_kst_date_idx on public.ai_usage_ledger (kst_date);

-- ---------------------------------------------------------------------------
-- 노트 이미지와 Storage 삭제 작업
-- ---------------------------------------------------------------------------
-- Notion 가져오기로 옮긴 본문 이미지만 기록한다(화면 업로드는 두지 않는다, 결정 9).
create table public.note_images (
  id bigint generated always as identity primary key,
  note_id bigint not null references public.notes (id) on delete cascade,
  notion_block_id text not null,
  storage_path text not null,
  alt text,
  created_at timestamptz not null default now(),
  unique (note_id, notion_block_id)
);

-- 이미지를 삭제하는 트랜잭션에서 작업을 넣고 Storage 객체 삭제 뒤 갱신한다.
-- 노트나 이미지 행을 참조하지 않아 그 행이 지워져도 남는다. 사용자 정보와 노트 본문은 담지 않는다.
create table public.storage_delete_jobs (
  id bigint generated always as identity primary key,
  bucket text not null,
  object_path text not null,
  status text not null default 'pending' check (status in ('pending', 'done', 'failed')),
  attempts integer not null default 0 check (attempts >= 0),
  last_error_kind text,
  created_at timestamptz not null default now(),
  done_at timestamptz
);

-- ---------------------------------------------------------------------------
-- 보안: RLS를 켜고 정책은 만들지 않는다. anon/authenticated는 행을 볼 수 없다.
-- ---------------------------------------------------------------------------
alter table public.profiles enable row level security;
alter table public.terms enable row level security;
alter table public.glossary_entries enable row level security;
alter table public.glossary_images enable row level security;
alter table public.ai_explanations enable row level security;
alter table public.term_views enable row level security;
alter table public.favorites enable row level security;
alter table public.favorite_events enable row level security;
alter table public.quiz_sets enable row level security;
alter table public.quiz_set_terms enable row level security;
alter table public.quiz_items enable row level security;
alter table public.quiz_answers enable row level security;
alter table public.quiz_followups enable row level security;
alter table public.reports enable row level security;
alter table public.ai_usage_ledger enable row level security;
alter table public.note_images enable row level security;
alter table public.storage_delete_jobs enable row level security;

revoke all on table
  public.profiles, public.terms, public.glossary_entries, public.glossary_images,
  public.ai_explanations, public.term_views, public.favorites, public.favorite_events,
  public.quiz_sets, public.quiz_set_terms, public.quiz_items, public.quiz_answers,
  public.quiz_followups, public.reports, public.ai_usage_ledger, public.note_images,
  public.storage_delete_jobs
  from anon, authenticated;

grant select, insert, update, delete on table
  public.profiles, public.terms, public.glossary_entries, public.glossary_images,
  public.ai_explanations, public.term_views, public.favorites, public.favorite_events,
  public.quiz_sets, public.quiz_set_terms, public.quiz_items, public.quiz_answers,
  public.quiz_followups, public.reports, public.ai_usage_ledger, public.note_images,
  public.storage_delete_jobs
  to service_role;

-- identity 시퀀스도 anon/authenticated 권한을 명시적으로 회수하고 service_role에만 준다.
revoke all on sequence
  public.terms_id_seq, public.glossary_images_id_seq, public.ai_explanations_id_seq,
  public.quiz_sets_id_seq, public.quiz_items_id_seq, public.reports_id_seq,
  public.ai_usage_ledger_id_seq, public.note_images_id_seq, public.storage_delete_jobs_id_seq
  from anon, authenticated;
grant usage on all sequences in schema public to service_role;
