export const subjects = ['네트워크', '운영체제', '데이터베이스']
export type Note = { id: number; title: string; subjects: string[]; date: string; body: string; sources: string[]; parent: string }
export type Term = { id: number; label: string; description: string; image?: string; placeholder?: boolean }
export type Report = { id: number; kind: '용어 설명' | '퀴즈 문항'; title: string; body: string; resolved: boolean }
export const noteBody = '브라우저가 주소를 입력받으면 먼저 DNS에 물어 서버의 위치를 찾아요. 찾은 위치로 패킷을 보내면 라우터가 길을 골라 전달해요.'
export const aiDescription = '하나의 연결을 여러 요청이 나눠 쓰는 방식이에요. 요청마다 연결을 새로 만들지 않아서 기다리는 시간이 줄어요. 합성 문구 예시예요.'
export const initialNotes: Note[] = [
  { id: 11, title: '예시 노트 · 요청이 서버까지 가는 길', subjects: ['네트워크'], date: '2026-10-14', body: noteBody, sources: ['https://example.test/doc'], parent: '' },
  { id: 12, title: '예시 노트 · 프로세스가 번갈아 실행되는 이유', subjects: ['운영체제'], date: '2026-10-09', body: '프로세스는 운영체제가 정한 순서에 따라 CPU를 번갈아 사용해요. 합성 문구 예시예요.', sources: [], parent: '' },
  { id: 13, title: '예시 노트 · 인덱스가 조회를 빠르게 하는 방식', subjects: ['데이터베이스'], date: '2026-10-02', body: '인덱스는 필요한 데이터를 빠르게 찾을 수 있도록 돕는 자료 구조예요. 합성 문구 예시예요.', sources: [], parent: '' },
  { id: 14, title: '예시 노트 · 캐시가 오래된 값을 돌려주는 경우', subjects: ['네트워크'], date: '2026-09-27', body: '캐시는 이전 응답을 저장해 다시 사용해요. 저장한 값과 원본 값이 다를 수 있어요. 합성 문구 예시예요.', sources: [], parent: '' },
]
export const initialAdminNotes: Note[] = [initialNotes[0],
  { ...initialNotes[1], title: '예시 노트 · 프로세스와 스레드', date: '2026-10-12' },
  { ...initialNotes[2], title: '예시 노트 · 캐시는 왜 빠를까', subjects: ['운영체제'], date: '2026-10-09' },
  { ...initialNotes[3], title: '예시 노트 · 컨테이너 기초', date: '2026-10-05' },
]
export const initialTerms: Term[] = [
  { id: 7, label: 'DNS', description: '도메인 이름을 서버의 숫자 주소로 바꿔 주는 이름 찾기 서비스예요.', placeholder: true },
  { id: 8, label: '패킷', description: '네트워크에서 데이터를 나누어 전달하는 작은 단위예요.' },
  { id: 9, label: '라우터', description: '패킷이 목적지에 도착하도록 다음 경로를 골라 주는 장치예요.' },
  { id: 10, label: '캐시', description: '이전에 받은 데이터를 가까운 곳에 저장해 다시 사용하는 방식이에요.' },
]
export const initialReports: Report[] = [
  { id: 1, kind: '용어 설명', title: 'TCP', body: '합성 AI 설명 예시: 데이터를 순서대로 보내 줘요.', resolved: false },
  { id: 2, kind: '퀴즈 문항', title: '합성 문항 예시', body: 'DNS를 한 문장으로 설명해 보세요.', resolved: false },
]
export function filterNotes(notes: Note[], subject: string): Note[] {
  return subject === '전체' ? notes : notes.filter((note) => note.subjects.includes(subject))
}
export function saveItem<T extends { id: number }>(items: T[], item: T): T[] {
  return items.some(({ id }) => id === item.id) ? items.map((old) => old.id === item.id ? item : old) : [...items, item]
}
