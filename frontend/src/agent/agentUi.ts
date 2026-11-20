// CS Agent 패널의 화면 상태와 도우미(MEG-258). 컴포넌트 파일과 나눠 둔다(빠른 새로 고침 규칙).
import type { AgentResult, AgentTurn } from './types.ts'

// 질문 문맥으로 붙일 노트 선택. start·end는 코드포인트 위치다(E27 selection).
export type AgentContextSelection = { noteId: number; revision: number; start: number; end: number; text: string }

// 패널을 닫았다 열어도 남겨야 하는 화면 상태. 노트 화면이 가진다.
export type AgentUi = {
  selection: AgentContextSelection | null
  // 선택 문장을 '제외'했다. 대화가 있으면 다음 질문부터 exclude_selection_ids로 보낸다.
  excluded: boolean
  draft: string
  // '이전 대화 보기'로 앞 턴을 펼쳤다.
  expanded: boolean
}

export const INITIAL_AGENT_UI: AgentUi = { selection: null, excluded: false, draft: '', expanded: false }

// 서버의 질문 글 한도(ai_turns 질문 글 1~1000자).
export const MAX_QUESTION = 1000

// 본문 절이 있는 결과. partial·correction의 한계·교정 카드는 T6d(MEG-260)에서 그린다. 여기서는 본문 절과 출처만 그린다.
export function sectionsOf(result: AgentResult | undefined) {
  if (result && (result.state === 'answered' || result.state === 'partial' || result.state === 'correction')) return result
  return null
}

// '답변에서 인용한 부분'(F6-4): 출처 번호가 붙은 문장을 답변에서 찾는다. 찾지 못하면 빈 글이다.
export function quoteOf(turn: AgentTurn | undefined, ref: number): string {
  const result = sectionsOf(turn?.result)
  if (!result) return ''
  const mark = `[${ref}]`
  for (const section of result.sections) {
    const at = section.body.indexOf(mark)
    if (at < 0) continue
    const before = section.body.slice(0, at)
    const start = Math.max(...['.', '?', '!', '\n'].map((stop) => before.lastIndexOf(stop))) + 1
    return section.body
      .slice(start, at + mark.length)
      .replace(/^\s*(?:[-*+]|\d+\.)\s+/, '')
      .replace(/[*_`#>]/g, '')
      .trim()
  }
  return ''
}
