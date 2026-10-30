// 운영자 노트 서버 호출을 모은 파일이다. 화면은 이 파일의 함수만 부른다.
//
// TODO(MEG-80): E15~E18 명세(MEG-27 첨부)를 받으면 아래 함수 본문을 apiFetch 호출로 바꾼다. 함수 모양(인자·반환)과 화면은 그대로 둔다.
// 지금은 명세가 저장소에 없어 경로·필드를 정할 수 없으므로 메모리 가짜 저장소로 화면을 먼저 확인한다. 새로 고치면 사라지고 합성 데이터만 담는다.
// 명세와 상관없이 정해진 것: 운영자 목록(E04)은 노트마다 is_published·revision이 오고, 저장할 때 revision이 서버와 다르면
// 409 conflict(detail stale_revision)다(backend/app/errors.py). 운영자 목록은 E04가 이미 구현되어 있어 가짜 저장소 대신 바로 붙일 수 있다.
import { ApiError } from '../../api/client.ts'

export type NoteSubject = { id: number; name: string }

export type OperatorNote = {
  id: number
  title: string
  studiedOn: string
  body: string
  subjects: NoteSubject[]
  isPublished: boolean
  revision: number
}

export type NoteListItem = Omit<OperatorNote, 'body'>

export type NoteInput = { title: string; studiedOn: string; body: string }

export type NoteList = { subjects: NoteSubject[]; notes: NoteListItem[] }

const NETWORK: NoteSubject = { id: 2, name: '네트워크' }
const OS: NoteSubject = { id: 1, name: '운영체제' }

// 합성 데이터. 실제 노트가 아니다. 과목은 목록에서 걸러 볼 때만 쓰고, 노트 폼에서는 고르지 않는다(여러 과목 선택이 확정되기 전).
let store: OperatorNote[] = [
  { id: 1, title: '예시 노트 · 요청이 서버까지 가는 길', studiedOn: '2026-10-14', body: '브라우저가 주소를 입력받으면 먼저 DNS에 물어 서버의 위치를 찾아요. 찾은 위치로 패킷을 보내면 라우터가 길을 골라 전달해요.', subjects: [NETWORK], isPublished: true, revision: 1 },
  { id: 2, title: '예시 노트 · 프로세스와 스레드', studiedOn: '2026-10-12', body: '프로세스는 실행 중인 프로그램이고, 스레드는 그 안에서 일하는 흐름이에요.', subjects: [OS], isPublished: true, revision: 1 },
  { id: 3, title: '예시 노트 · 캐시는 왜 빠를까', studiedOn: '2026-10-09', body: '자주 쓰는 데이터를 가까운 곳에 두면 다시 가져오는 시간이 줄어요.', subjects: [OS], isPublished: true, revision: 1 },
  { id: 4, title: '예시 노트 · 컨테이너 기초', studiedOn: '2026-10-05', body: '컨테이너는 프로그램과 실행 환경을 한 묶음으로 만든 거예요.', subjects: [NETWORK], isPublished: false, revision: 1 },
]
let nextId = 5

function notFound(): ApiError {
  return new ApiError(404, { code: 'not_found', message: 'Resource not found', request_id: '' })
}

function stale(): ApiError {
  return new ApiError(409, { code: 'conflict', message: 'The note has changed since it was loaded', detail: 'stale_revision', request_id: '' })
}

function withoutBody({ body: _body, ...item }: OperatorNote): NoteListItem {
  return item
}

// E04(운영자): 과목 목록과 노트 목록. subjectId가 있으면 그 과목의 노트만 준다. 과목 목록은 걸러도 전부 온다.
export async function listNotes(subjectId: number | null): Promise<NoteList> {
  const notes = store.filter((note) => subjectId === null || note.subjects.some((subject) => subject.id === subjectId))
  return { subjects: [OS, NETWORK], notes: notes.map(withoutBody) }
}

// 편집 화면이 노트 하나를 불러온다. 없으면 404다.
export async function getNote(id: number): Promise<OperatorNote> {
  const note = store.find((item) => item.id === id)
  if (!note) throw notFound()
  return { ...note, subjects: [...note.subjects] }
}

// 노트 저장. id가 없으면 새로 쓰고(비공개로 시작), 있으면 고친다. 고칠 때 revision이 서버와 다르면 409 stale_revision이다.
export async function saveNote(id: number | null, input: NoteInput, revision: number | null): Promise<OperatorNote> {
  if (id === null) {
    const created: OperatorNote = { id: nextId++, ...input, subjects: [], isPublished: false, revision: 1 }
    store = [...store, created]
    return { ...created }
  }
  const existing = store.find((note) => note.id === id)
  if (!existing) throw notFound()
  if (revision !== existing.revision) throw stale()
  const updated: OperatorNote = { ...existing, ...input, revision: existing.revision + 1 }
  store = store.map((note) => (note.id === id ? updated : note))
  return { ...updated }
}

// 노트 삭제
export async function deleteNote(id: number): Promise<void> {
  if (!store.some((note) => note.id === id)) throw notFound()
  store = store.filter((note) => note.id !== id)
}

// 공개 여부 전환. 제목·본문을 고치는 것이 아니라서 revision은 그대로다.
export async function setPublished(id: number, isPublished: boolean): Promise<NoteListItem> {
  const existing = store.find((note) => note.id === id)
  if (!existing) throw notFound()
  const updated = { ...existing, isPublished }
  store = store.map((note) => (note.id === id ? updated : note))
  return withoutBody(updated)
}

// 확인용: 다른 곳에서 이 노트를 고친 것처럼 서버 쪽 내용을 바꾼다(가짜 저장소에서만 있다). 충돌 안내를 시험할 때 쓴다.
export function simulateRemoteChange(id: number): void {
  store = store.map((note) => (note.id === id ? { ...note, title: `${note.title} (다른 곳에서 수정)`, revision: note.revision + 1 } : note))
}
