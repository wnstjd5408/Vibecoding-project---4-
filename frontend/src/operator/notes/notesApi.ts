// 운영자 노트 서버 호출을 모은 파일이다. 화면은 이 파일의 함수만 부른다. 가짜 응답은 VITE_API_MOCK=true일 때 apiFetch가 고른다.
//
// 요청·응답 모양은 backend/app/admin_notes.py(E15~E18, MEG-79)와 notes.py(E04)를 따른다. 서버의 요청 모델은 모르는 필드를 거부(extra="forbid")한다.
//  - 목록 E04(`GET /api/notes`): 운영자는 노트마다 is_published·revision이 온다.
//  - 편집 화면의 노트 E15(`GET /api/admin/notes/{id}`): revision·제목·학습일·본문·공개 여부. 없으면 404 not_found다.
//  - 작성 E16(`POST /api/admin/notes`): title이 필수다. 응답은 { id, revision }이다.
//  - 수정·공개 전환 E17(`PATCH /api/admin/notes/{id}`): 보낸 필드만 바꾼다. 충돌 검사 필드는 expected_revision이고, 서버의 revision과 다르면
//    409 conflict(detail stale_revision)다. 이 값을 보내지 않으면 서버는 충돌 검사를 건너뛰므로 수정·공개 전환은 항상 보낸다.
//    응답은 { id, revision, is_published }이다.
//  - 삭제 E18(`DELETE /api/admin/notes/{id}`): 204, 없으면 404다.
// 서버는 UPDATE마다 revision을 올린다(공개 전환 포함).
import type { ApiRequestInit } from '../../api/client.ts'

// useOperatorApi()가 돌려주는 함수. 권한 상실(401·403)이면 로그인 상태를 다시 읽고 오류는 그대로 던진다.
export type OperatorFetch = <T>(path: string, init?: ApiRequestInit) => Promise<T>

export type NoteSubject = { id: number; name: string }

// 편집 화면의 노트(E15)
export type OperatorNote = {
  id: number
  title: string
  studiedOn: string
  body: string
  subjects: NoteSubject[]
  revision: number
}

// 목록의 노트(E04, 운영자)
export type NoteListItem = {
  id: number
  title: string
  studiedOn: string
  subjects: NoteSubject[]
  isPublished: boolean
  revision: number
}

export type NoteInput = { title: string; studiedOn: string; body: string }

export type NoteList = { subjects: NoteSubject[]; notes: NoteListItem[] }

// 서버 규칙(backend/app/admin_notes.py): 제목 1~300자, 본문 200,000자 이하
export const TITLE_MAX = 300
export const BODY_MAX = 200_000

type ServerNoteListItem = {
  id: number
  title: string
  studied_on: string | null
  subjects: NoteSubject[]
  is_published?: boolean
  revision?: number
}

// E04(운영자): 과목 목록과 노트 목록. subjectId가 있으면 그 과목의 노트만 준다. 과목 목록은 걸러도 전부 온다.
export async function listNotes(operatorFetch: OperatorFetch, subjectId: number | null): Promise<NoteList> {
  const result = await operatorFetch<{ subjects: NoteSubject[]; notes: ServerNoteListItem[] }>('/api/notes', {
    query: { subject_id: subjectId ?? undefined },
  })
  return {
    subjects: result.subjects.map(({ id, name }) => ({ id, name })),
    notes: result.notes.map((note) => ({
      id: note.id,
      title: note.title,
      studiedOn: note.studied_on ?? '',
      subjects: note.subjects,
      isPublished: note.is_published === true,
      revision: note.revision ?? 0,
    })),
  }
}

// E15: 편집 화면이 노트 하나를 불러온다. 없으면 404 not_found다.
export async function getNote(operatorFetch: OperatorFetch, id: number): Promise<OperatorNote> {
  const note = await operatorFetch<{
    id: number
    revision: number
    title: string
    studied_on: string | null
    subjects: NoteSubject[]
    body_markdown: string
  }>(`/api/admin/notes/${id}`)
  return {
    id: note.id,
    title: note.title,
    studiedOn: note.studied_on ?? '',
    body: note.body_markdown,
    subjects: note.subjects,
    revision: note.revision,
  }
}

// E16·E17: id가 없으면 새로 쓰고, 있으면 고친다. 고칠 때 expected_revision이 서버의 revision과 다르면 409 conflict(detail stale_revision)다.
export async function saveNote(operatorFetch: OperatorFetch, id: number | null, input: NoteInput, revision: number | null): Promise<void> {
  const fields = { title: input.title, studied_on: input.studiedOn, body_markdown: input.body }
  if (id === null) {
    await operatorFetch('/api/admin/notes', { method: 'POST', body: fields })
    return
  }
  await operatorFetch(`/api/admin/notes/${id}`, { method: 'PATCH', body: { expected_revision: revision, ...fields } })
}

// E18: 노트 삭제
export async function deleteNote(operatorFetch: OperatorFetch, id: number): Promise<void> {
  await operatorFetch(`/api/admin/notes/${id}`, { method: 'DELETE' })
}

// E17: 공개 여부 전환. 제목·본문은 보내지 않는다. 서버는 UPDATE마다 revision을 올리므로 호출한 쪽이 목록을 다시 읽는다.
export async function setPublished(operatorFetch: OperatorFetch, note: Pick<NoteListItem, 'id' | 'revision'>, isPublished: boolean): Promise<void> {
  await operatorFetch(`/api/admin/notes/${note.id}`, { method: 'PATCH', body: { expected_revision: note.revision, is_published: isPublished } })
}
