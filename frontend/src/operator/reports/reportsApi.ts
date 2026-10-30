// 신고 서버 호출(API spec v0.2 E25·E26)을 모은 파일이다. 화면은 이 파일의 함수만 부른다.
//
// TODO(MEG-84): E25·E26 명세(MEG-27 첨부)를 받으면 아래 함수 본문을 apiFetch 호출로 바꾼다. 함수 모양(인자·반환)과 화면은 그대로 둔다.
// 지금은 명세가 저장소에 없어 경로·응답 필드·오류 code를 정할 수 없으므로 메모리 가짜 저장소로 화면을 먼저 확인한다.
// 티켓에 적힌 것은 E26 요청 본문의 invalidate_explanation 하나뿐이라 그 부분만 buildResolveBody로 확정해 둔다.
// 이 저장소는 새로 고치면 사라지고 합성 데이터만 담는다.

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
