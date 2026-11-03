// 운영자 노트 서버 호출을 모은 파일이다. 화면은 이 파일의 함수만 부른다. 가짜 응답은 VITE_API_MOCK=true일 때 apiFetch가 고른다.
//
// 읽기는 이미 있는 API를 부른다: 목록은 E04(운영자는 노트마다 is_published·revision이 온다), 편집 화면의 노트 한 개는 E05(운영자는
// 비공개 노트도 읽고 revision·제목·학습일·본문이 온다). 편집 전용 읽기 E15는 백엔드에 아직 없어 E05를 쓴다.
//
// 쓰기(작성·수정·삭제·공개 전환)는 E16~E18이다. 경로와 메서드는 docs/architecture/architecture.json에 있지만 요청·응답 필드 명세는
// 저장소에 없고 백엔드에도 아직 없다. 그래서 아래 요청 본문의 필드 이름은 **추정**이다.
// TODO(MEG-80): E16~E18이 구현되면 요청 본문(title·studied_on·body_markdown·revision·is_published)과 응답을 명세·서버 코드와 대조한다.
// 서버에 라우트가 없는 동안 실제 모드의 쓰기는 404 not_found로 실패하고 화면은 저장 실패로 알린다(성공으로 처리하지 않는다).
import type { ApiRequestInit } from '../../api/client.ts'

// useOperatorApi()가 돌려주는 함수. 권한 상실(401·403)이면 로그인 상태를 다시 읽고 오류는 그대로 던진다.
export type OperatorFetch = <T>(path: string, init?: ApiRequestInit) => Promise<T>

export type NoteSubject = { id: number; name: string }

// 편집 화면의 노트(E05). 공개 여부는 E05에 없고 목록(E04)에만 있다.
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

// E05: 편집 화면이 노트 하나를 불러온다. 운영자는 비공개 노트도 읽는다. 없으면 404 not_found다.
export async function getNote(operatorFetch: OperatorFetch, id: number): Promise<OperatorNote> {
  const note = await operatorFetch<{
    id: number
    revision: number
    title: string
    studied_on: string | null
    subjects: NoteSubject[]
    body_markdown: string
  }>(`/api/notes/${id}`)
  return {
    id: note.id,
    title: note.title,
    studiedOn: note.studied_on ?? '',
    body: note.body_markdown,
    subjects: note.subjects,
    revision: note.revision,
  }
}

// E16·E17(필드 이름은 추정): id가 없으면 새로 쓰고, 있으면 고친다. 고칠 때 revision이 서버와 다르면 409 conflict(detail stale_revision)다.
export async function saveNote(operatorFetch: OperatorFetch, id: number | null, input: NoteInput, revision: number | null): Promise<void> {
  const fields = { title: input.title, studied_on: input.studiedOn, body_markdown: input.body }
  if (id === null) {
    await operatorFetch('/api/admin/notes', { method: 'POST', body: fields })
    return
  }
  await operatorFetch(`/api/admin/notes/${id}`, { method: 'PATCH', body: { revision, ...fields } })
}

// E18: 노트 삭제
export async function deleteNote(operatorFetch: OperatorFetch, id: number): Promise<void> {
  await operatorFetch(`/api/admin/notes/${id}`, { method: 'DELETE' })
}

// E17(필드 이름은 추정): 공개 여부 전환. 제목·본문은 보내지 않는다. 서버는 UPDATE마다 revision을 올리므로 호출한 쪽이 목록을 다시 읽는다.
export async function setPublished(operatorFetch: OperatorFetch, note: Pick<NoteListItem, 'id' | 'revision'>, isPublished: boolean): Promise<void> {
  await operatorFetch(`/api/admin/notes/${note.id}`, { method: 'PATCH', body: { revision: note.revision, is_published: isPublished } })
}
