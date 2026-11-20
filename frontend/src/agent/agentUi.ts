// CS Agent 패널의 화면 상태와 도우미(MEG-258). 컴포넌트 파일과 나눠 둔다(빠른 새로 고침 규칙).
import type { AgentState } from './conversation.ts'
import type { AgentResult, AgentTurn } from './types.ts'

// 질문 문맥으로 붙일 노트 선택. start·end는 코드포인트 위치다(E27 selection).
export type AgentContextSelection = { noteId: number; revision: number; start: number; end: number; text: string }

// 패널을 닫았다 열어도 남겨야 하는 화면 상태. 노트 화면이 가진다.
export type AgentUi = {
  selection: AgentContextSelection | null
  // 대화를 만들기 전에 선택 문장을 '제외'했다(질문 준비 화면).
  excluded: boolean
  // 대화의 선택 문맥 가운데 '제외'한 것(selection_id). 다음 질문부터 exclude_selection_ids로 보낸다.
  excludedIds: string[]
  // '현재 대화에 추가'로 고른 새 문장(F6-8, 결정 20). 다음 질문의 add_selections로 보내고, 답을 받으면 비운다.
  added: AgentContextSelection[]
  // 대화 중에 노트에서 새로 고른 문장. 고르기 전까지 '새로 선택한 내용을 어떻게 쓸까요?' 카드를 보이고 보내기를 잠근다(F6-8).
  candidate: AgentContextSelection | null
  draft: string
  // '이전 대화 보기'로 앞 턴을 펼쳤다.
  expanded: boolean
}

export const INITIAL_AGENT_UI: AgentUi = { selection: null, excluded: false, excludedIds: [], added: [], candidate: null, draft: '', expanded: false }

// 새 대화를 열 때 비우는 문맥 상태
export const FRESH_CONTEXT: Pick<AgentUi, 'excluded' | 'excludedIds' | 'added' | 'candidate' | 'expanded'> = {
  excluded: false,
  excludedIds: [],
  added: [],
  candidate: null,
  expanded: false,
}

// 노트 접근 변경(S9, F6-15): 대화·노트·턴을 볼 수 없다(E27~E31 404). 패널과 노트 화면이 함께 닫힌 안내로 바꾼다.
export function agentAccessLost(state: AgentState): boolean {
  return state.failure?.kind === 'not_found' || state.loadFailure?.kind === 'not_found'
}

// 서버의 질문 글 한도(ai_turns 질문 글 1~1000자).
export const MAX_QUESTION = 1000

// 본문 절이 있는 결과(answered·partial·correction). partial의 한계와 correction의 교정은 AgentPanel이 따로 그린다(MEG-260).
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
