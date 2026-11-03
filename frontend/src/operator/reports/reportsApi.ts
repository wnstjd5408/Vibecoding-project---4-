// 신고 서버 호출(API spec v0.2 E25·E26)과 사전에 바른 설명 넣기(E20·E22)를 모은 파일이다. 화면은 이 파일의 함수만 부른다.
// 요청 본문과 응답 모양은 backend/app/admin_reports.py·admin_glossary.py를 따른다. 가짜 응답은 VITE_API_MOCK=true일 때 apiFetch가 고른다.
import { ApiError } from '../../api/client.ts'
import type { ApiRequestInit } from '../../api/client.ts'

// useOperatorApi()가 돌려주는 함수. 권한 상실(401·403)이면 로그인 상태를 다시 읽고 오류는 그대로 던진다.
export type OperatorFetch = <T>(path: string, init?: ApiRequestInit) => Promise<T>

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

// E26 요청 본문. 처리 상태는 resolved 하나뿐이고 서버가 필수로 받는다.
export function buildResolveBody(options: ResolveOptions): { status: 'resolved'; invalidate_explanation: boolean } {
  return { status: 'resolved', invalidate_explanation: options.invalidateExplanation }
}

// E25 응답의 신고 하나. 신고자는 내지 않는다.
type ReportTarget =
  | { type: 'ai_explanation'; id: number; term_key_snapshot: string; body: string }
  | { type: 'quiz_item'; id: number; question: string; answer: string }
type ServerReport = { id: number; status: ReportStatus; body: string; target: ReportTarget }
type ReportPage = { reports: ServerReport[]; next_cursor: string | null }

function toReport(item: ServerReport): Report {
  const resolved = item.status === 'resolved'
  if (item.target.type === 'ai_explanation') {
    return { id: item.id, kind: '용어 설명', title: item.target.term_key_snapshot, body: item.target.body, resolved }
  }
  return { id: item.id, kind: '문항', title: item.target.question, body: `정답: ${item.target.answer}`, resolved }
}

// 한 번에 받을 쪽 수의 상한. 신고가 이보다 많으면 나머지는 목록에 나오지 않는다(100건씩 20쪽).
const MAX_PAGES = 20

// E25: 신고 목록. status가 열림이면 처리 전, 처리됨이면 처리 후 신고만 준다. next_cursor가 있으면 이어서 받는다.
export async function listReports(operatorFetch: OperatorFetch, status: ReportStatus): Promise<Report[]> {
  const reports: Report[] = []
  let cursor: string | undefined
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const result = await operatorFetch<ReportPage>('/api/admin/reports', { query: { status, limit: 100, cursor } })
    reports.push(...result.reports.map(toReport))
    if (!result.next_cursor) break
    cursor = result.next_cursor
  }
  return reports
}

// E26: 신고를 처리 완료로 바꾼다. 이미 처리된 신고에 다시 보내도 200이다.
export async function resolveReport(operatorFetch: OperatorFetch, id: number, options: ResolveOptions): Promise<void> {
  await operatorFetch(`/api/admin/reports/${id}`, { method: 'PATCH', body: buildResolveBody(options) })
}

// 신고 하나. 사전에 바른 설명 넣기(F5-3) 화면이 신고된 내용을 보여 줄 때 쓴다. 신고 한 건을 주는 엔드포인트가 없어 E25 목록에서 찾는다.
// 없으면 404 not_found다.
export async function getReport(operatorFetch: OperatorFetch, id: number): Promise<Report> {
  for (const status of ['open', 'resolved'] as const) {
    const found = (await listReports(operatorFetch, status)).find((report) => report.id === id)
    if (found) return found
  }
  throw new ApiError(404, { code: 'not_found', message: 'Resource not found', request_id: '' })
}

export type DictionaryEntryInput = { label: string; description: string }

// 설명은 저장했지만 이미지를 올리지 못했다. 같은 내용으로 다시 저장하면 설명을 덮어쓰고(E20은 같은 이름이면 고친다) 이미지를 다시 올린다.
export class ImageNotSavedError extends Error {
  constructor(cause: unknown) {
    super('Dictionary entry saved but its image was not', { cause })
    this.name = 'ImageNotSavedError'
  }
}

// 신고된 용어 설명에 바른 설명을 사전으로 저장한다(F5-3). E20으로 용어 이름과 설명을 저장하고, 이미지가 있으면 E22로 올린다.
// 같은 이름의 용어가 있으면 그 용어의 사전 설명을 덮어쓴다. 신고 상태는 바뀌지 않는다. 신고 목록에서 따로 처리됨으로 바꾼다.
export async function saveDictionaryEntry(operatorFetch: OperatorFetch, input: DictionaryEntryInput, image: File | null): Promise<void> {
  const saved = await operatorFetch<{ term: { id: number } }>('/api/admin/glossary', {
    method: 'POST',
    body: { label: input.label, body_markdown: input.description },
  })
  if (!image) return
  const form = new FormData()
  form.append('file', image)
  try {
    await operatorFetch(`/api/admin/glossary/${saved.term.id}/images`, { method: 'POST', body: form })
  } catch (failure) {
    throw new ImageNotSavedError(failure)
  }
}
