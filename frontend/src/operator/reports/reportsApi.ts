// 신고 서버 호출(API spec v0.2 E25·E26)을 모은 파일이다. 화면은 이 파일의 함수만 부른다.
//
// TODO(MEG-84): E25·E26 명세(MEG-27 첨부)를 받으면 아래 함수 본문을 apiFetch 호출로 바꾼다. 함수 모양(인자·반환)과 화면은 그대로 둔다.
// 지금은 명세가 저장소에 없어 경로·응답 필드·오류 code를 정할 수 없으므로 메모리 가짜 저장소로 화면을 먼저 확인한다.
// 티켓에 적힌 것은 E26 요청 본문의 invalidate_explanation 하나뿐이라 그 부분만 buildResolveBody로 확정해 둔다.
// 이 저장소는 새로 고치면 사라지고 합성 데이터만 담는다.
import { ApiError } from '../../api/client.ts'

// 신고된 것의 종류. 목업의 "용어 설명"과 "문항"이다.
export type ReportKind = '용어 설명' | '문항'

export type Report = {
  id: number
  kind: ReportKind
  title: string
  body: string
  resolved: boolean
}

export type ReportStatus = 'open' | 'resolved'

export type ResolveOptions = {
  // 처리하면서 이 신고의 AI 설명도 무효화할지(Q-N7). 기본은 끈다.
  invalidateExplanation: boolean
}

// E26 요청 본문
export function buildResolveBody(options: ResolveOptions): { invalidate_explanation: boolean } {
  return { invalidate_explanation: options.invalidateExplanation }
}

// 합성 데이터. 실제 신고가 아니다.
let store: Report[] = [
  { id: 1, kind: '용어 설명', title: 'TCP', body: '합성 AI 설명 예시: 데이터를 순서대로 보내 줘요.', resolved: false },
  { id: 2, kind: '문항', title: '합성 문항 예시', body: '합성 문항 본문 예시: 이 문항의 정답이 맞는지 확인해 주세요.', resolved: false },
  { id: 3, kind: '용어 설명', title: 'DNS', body: '합성 AI 설명 예시: 이미 처리된 신고예요.', resolved: true },
]

// 가장 최근 E26 요청. 처리할 때 무엇을 보냈는지 확인하는 데 쓴다(가짜 저장소에서만 있다).
let lastResolve: { id: number; body: { invalidate_explanation: boolean } } | null = null
export function getLastResolveRequest() {
  return lastResolve
}

// E25: 신고 목록. status가 열림이면 처리 전, 처리됨이면 처리 후 신고만 준다.
export async function listReports(status: ReportStatus): Promise<Report[]> {
  return store.filter((report) => report.resolved === (status === 'resolved')).map((report) => ({ ...report }))
}

// E26: 신고를 처리 완료로 바꾼다.
export async function resolveReport(id: number, options: ResolveOptions): Promise<void> {
  lastResolve = { id, body: buildResolveBody(options) }
  store = store.map((report) => (report.id === id ? { ...report, resolved: true } : report))
}

// 신고 하나. 사전에 바른 설명 넣기(F5-3) 화면이 신고된 내용을 보여 줄 때 쓴다. 없으면 404다.
// TODO(MEG-84): 명세를 받으면 E25 목록에서 찾을지 별도 조회가 있는지 확인한다.
export async function getReport(id: number): Promise<Report> {
  const report = store.find((item) => item.id === id)
  if (!report) throw new ApiError(404, { code: 'not_found', message: 'Resource not found', request_id: '' })
  return { ...report }
}

export type DictionaryEntryInput = { label: string; description: string }

// 가장 최근에 사전에 저장한 내용(가짜 저장소에서만 있다). 무엇을 저장했는지 확인하는 데 쓴다.
let lastDictionaryEntry: { reportId: number; input: DictionaryEntryInput; image: string | null } | null = null
export function getLastDictionaryEntry() {
  return lastDictionaryEntry
}

// 신고된 용어 설명에 바른 설명을 사전으로 저장한다(F5-3). 같은 이름의 용어가 있으면 그 용어의 사전 설명을 덮어쓰고, 없으면 새로 만든다(목업과 같다).
// 신고 상태는 바뀌지 않는다. 신고 목록에서 따로 처리됨으로 바꾼다.
// TODO(MEG-84): 사전 저장 API(용어 사전 E19~E23 중) 명세를 받으면 apiFetch 호출로 바꾼다. 지금은 용어 사전 화면(MEG-82)의 저장소와 이어지지 않는다.
export async function saveDictionaryEntry(reportId: number, input: DictionaryEntryInput, image: File | null): Promise<void> {
  if (!store.some((report) => report.id === reportId)) throw new ApiError(404, { code: 'not_found', message: 'Resource not found', request_id: '' })
  lastDictionaryEntry = { reportId, input, image: image ? image.name : null }
}
