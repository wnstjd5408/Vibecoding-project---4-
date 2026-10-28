-- CS 학습 노트 스키마 보강 v06 (MEG-60, API spec v0.2 9절 S4·S5·S6·S7·S8·S10, Q-N5)
-- 접근 모델은 앞 마이그레이션과 같다: FastAPI(service_role)만 DB에 접근한다.
-- 길이 상한 중 spec에 숫자가 없는 값(사전 본문 200,000자, AI 설명 본문 20,000자, 꼬리 질문 1,000자)은
-- MEG-60 제안값이다(2026-10-28 김준성 수락). 숫자는 시험 뒤 조정할 수 있다.

-- ---------------------------------------------------------------------------
-- 1. reports: 시각 열과 대상별 open 신고 중복 방지 (S5·S6)
-- ---------------------------------------------------------------------------
alter table public.reports
  add column created_at timestamptz not null default now(),
  -- 운영자가 처리(E26)할 때 채운다.
  add column resolved_at timestamptz,
  add constraint reports_body_length_check check (char_length(body) <= 1000);

-- 같은 사용자·같은 대상의 open 신고는 하나다. 처리된 신고는 여러 개 남을 수 있다.
create unique index reports_open_ai_explanation_idx
  on public.reports (user_id, ai_explanation_id)
  where status = 'open' and ai_explanation_id is not null;

create unique index reports_open_quiz_item_idx
  on public.reports (user_id, quiz_item_id)
  where status = 'open' and quiz_item_id is not null;

-- ---------------------------------------------------------------------------
-- 2. quiz_followups: 슬롯 예약 시각 (S4)과 길이 (S10)
-- ---------------------------------------------------------------------------
alter table public.quiz_followups
  -- 슬롯을 예약한 시각. 질문이 비어 있는 오래된 슬롯을 찾아 지울 때 쓴다.
  add column created_at timestamptz not null default now(),
  add constraint quiz_followups_question_length_check
    check (question is null or char_length(question) <= 1000),
  add constraint quiz_followups_user_answer_length_check
    check (user_answer is null or char_length(user_answer) <= 1000);

-- ---------------------------------------------------------------------------
-- 3. quiz_items: 한 세트에서 용어당 문항 하나 (S7)
-- ---------------------------------------------------------------------------
-- 용어가 지워져 term_id가 null인 문항은 제외한다. 표시 순서는 id 순서다.
create unique index quiz_items_set_term_idx
  on public.quiz_items (set_id, term_id)
  where term_id is not null;

-- ---------------------------------------------------------------------------
-- 4. terms.key: 서버 정규화 함수의 결과만 받는다 (S8, 기술 검토 5절)
-- ---------------------------------------------------------------------------
-- 유니코드 NFC, 영문(ASCII) 소문자, 공백 정리(공백 문자는 띄어쓰기 한 칸만, 앞뒤 공백 없음).
-- 영문 외 문자의 대소문자는 정규화 대상이 아니라 translate로 ASCII만 확인한다.
alter table public.terms
  add constraint terms_key_normalized_check check (
    key = normalize(key, NFC)
    and key = translate(key, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')
    and key = btrim(regexp_replace(key, '\s+', ' ', 'g'))
  );

-- ---------------------------------------------------------------------------
-- 5. 입력 길이 (S10). API가 먼저 막고 DB는 마지막 방어선이다.
-- ---------------------------------------------------------------------------
alter table public.quiz_answers
  add constraint quiz_answers_user_answer_length_check check (char_length(user_answer) <= 1000);

-- 노트 본문 200,000자는 API spec 10절 Q9의 임시값이다.
alter table public.notes
  add constraint notes_body_markdown_length_check check (char_length(body_markdown) <= 200000);

alter table public.glossary_entries
  add constraint glossary_entries_body_markdown_length_check check (char_length(body_markdown) <= 200000);

alter table public.ai_explanations
  add constraint ai_explanations_body_length_check check (char_length(body) <= 20000);

-- ---------------------------------------------------------------------------
-- 6. 노트 이미지 Storage 삭제 작업 기록 (S1·S13, 기술 검토 4절)
-- ---------------------------------------------------------------------------
-- 노트를 지우기 전에 같은 트랜잭션에서 부른다. 그 노트의 이미지마다 삭제 작업(pending)을 넣고 넣은 개수를 돌려준다.
-- 노트 삭제와 AI 설명 무효화는 하지 않는다. 노트 삭제 함수(MEG-79)가 이 함수를 안에서 불러 한 트랜잭션으로 묶는다.
-- 버킷 이름은 코드 상수라 인자로 받는다(S13).
create function public.enqueue_note_image_delete_jobs(p_note_id bigint, p_bucket text)
returns integer
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_count integer;
begin
  insert into public.storage_delete_jobs (bucket, object_path)
  select p_bucket, ni.storage_path
  from public.note_images ni
  where ni.note_id = p_note_id;

  get diagnostics v_count = row_count;
  return v_count;
end;
$$;

revoke execute on function public.enqueue_note_image_delete_jobs(bigint, text) from public, anon, authenticated;
grant execute on function public.enqueue_note_image_delete_jobs(bigint, text) to service_role;

-- ---------------------------------------------------------------------------
-- 7. 원장 멱등 키 형식 (Q-N5, S2). v05 주석 "{논리 요청 id}:{attempt_no}"를 아래로 대체한다.
-- ---------------------------------------------------------------------------
-- 끝자리는 모두 attempt_no(= 호출 안 재시도 번호 + 1)다.
--   E09 설명:      {user_id}:{Idempotency-Key}:{attempt_no}        Idempotency-Key는 클라이언트가 보내는 UUID
--   E11 퀴즈:      {user_id}:quiz:{set_id}:{attempt}:{attempt_no}  attempt는 quiz_sets.attempt(선점 번호)
--   E13 꼬리 질문: {user_id}:followup:{요청 id}:{attempt_no}       요청 id는 서버가 만든다(API spec 1.7)
comment on column public.ai_usage_ledger.idempotency_key is
  'E09 {user_id}:{Idempotency-Key}:{attempt_no} / E11 {user_id}:quiz:{set_id}:{quiz_sets.attempt}:{attempt_no} / E13 {user_id}:followup:{서버 요청 id}:{attempt_no}';
comment on column public.ai_usage_ledger.attempt_no is
  '호출 안 재시도 번호 + 1. 첫 시도가 1이고 사용자별 하루 한도 N은 attempt_no = 1인 행만 센다';
