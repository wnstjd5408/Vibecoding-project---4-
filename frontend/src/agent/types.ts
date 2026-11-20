// CS Agent 'AI에게 질문'의 요청·응답 모양(API spec v0.2 3~6절 E27~E32, MEG-255).
// 서버 구현(backend/app/agent.py, agent_access.py, agent_turns.py, agent_sources.py)이 실제로 내보내는 필드에 맞췄다.
// 화면은 이 타입만 쓰고, 서버 필드 이름이 바뀌면 이 파일과 agent/api.ts만 고친다.

export type AgentOrigin = 'note' | 'wiki' | 'none'
export type SourceKind = 'note' | 'wiki'

// 3절 selection. start·end는 노트 원문의 유니코드 코드포인트 위치이고 끝은 포함하지 않는다(E09와 같은 규칙).
export type AgentSelection = {
  selection_id: string
  note_id: number
  note_revision: number
  start: number
  end: number
  text_preview: string
  revision_changed: boolean
}

// 3절 conversation(E27 응답, E28 응답의 앞부분).
export type AgentConversation = {
  conversation_id: string
  topic_label: string
  origin: AgentOrigin
  note?: { note_id: number; note_revision: number; title: string }
  context_selections: AgentSelection[]
  created_at: string
}

export type QuestionKind = 'free' | 'suggested' | 'preset'
export type QuestionPreset = 'detail' | 'simple' | 'example'

// 가린 턴(hidden)의 추천 질문은 text가 빠진다(agent_access.turn_payload).
export type AgentQuestion = {
  kind: QuestionKind
  text?: string
  preset?: QuestionPreset
  from_turn_id?: string
}

export type TurnStatus = 'running' | 'completed' | 'cancelled' | 'failed'
// failed의 원인. limit는 사용 제한 화면(S12), 나머지는 요청 실패 화면(S8)이다.
export type TurnFailure = 'error' | 'interrupted' | 'limit'
export type AgentStep = 'understand' | 'retrieve' | 'compose'

// 5.2 출처. 출처를 열 때는 E32(turn_id + ref)를 부른다. 모델이 만든 주소는 쓰지 않는다.
export type AgentSource = {
  ref: number
  source_kind: SourceKind
  title: string
  section?: string
  excerpt?: string
  cited_revision: number
}

// 5.3 그림. 노트 근거 기간에는 diagram만 온다. image의 모양은 spec Q1에서 정한다.
export type AgentFigure = {
  figure_id?: string
  kind?: 'image' | 'diagram'
  mermaid?: string
  image?: unknown
  caption: string
  alt_text: string
  source_refs: number[]
  // 그림을 둘 절 번호(1부터). 서버 출력 검증이 sections 범위 안인지 확인한다.
  after_section: number
}

export type AgentSection = { heading?: string; body: string }

// 5절 turn.result. state마다 담는 필드가 다르다.
export type AnsweredResult = {
  state: 'answered'
  sections: AgentSection[]
  sources?: AgentSource[]
  figures?: AgentFigure[]
  suggestions?: string[]
}
export type PartialResult = {
  state: 'partial'
  sections: AgentSection[]
  limitation: string
  sources?: AgentSource[]
  figures?: AgentFigure[]
  suggestions?: string[]
}
export type ClarifyResult = {
  state: 'clarify'
  clarify: { prompt: string; options: { option_id: string; label: string }[] }
}
export type NoEvidenceResult = {
  state: 'no_evidence'
  notice_code: string
  next_actions: string[]
}
export type CorrectionResult = {
  state: 'correction'
  sections: AgentSection[]
  corrections: { note_excerpt: string; corrected: string; source_refs: number[] }[]
  unresolved?: string[]
  sources?: AgentSource[]
  figures?: AgentFigure[]
  suggestions?: string[]
}
export type TopicCheckResult = {
  state: 'topic_check'
  topic_check: { current_topic: string }
}
export type AgentResult =
  | AnsweredResult
  | PartialResult
  | ClarifyResult
  | NoEvidenceResult
  | CorrectionResult
  | TopicCheckResult

// 3절 turn(E28 turns[], E29 result 이벤트, E30 응답). 가린 턴은 result가 없고 hidden이 있다.
export type AgentTurn = {
  turn_id: string
  seq: number
  question: AgentQuestion
  status: TurnStatus
  created_at: string
  finished_at?: string
  failure?: TurnFailure
  // running일 때 지금 단계(E30). 스트림이 끊긴 뒤 화면이 단계 표시를 이어 갈 때 쓴다.
  step?: AgentStep
  result?: AgentResult
  hidden?: { reason: 'source_revoked'; retry_allowed: boolean }
}

// E28 GET /api/ai/conversations/{conversation_id}
export type AgentConversationWithTurns = AgentConversation & { turns: AgentTurn[] }

// E30 GET /api/ai/turns/{turn_id}. running이면 다시 조회할 간격(초)이 함께 온다.
export type AgentTurnRead = AgentTurn & { retry_after_seconds?: number }

// E31 POST /api/ai/turns/{turn_id}/cancel
export type AgentCancelResponse = { turn_id: string; status: 'cancelled'; question: AgentQuestion }

// E32 GET /api/ai/turns/{turn_id}/sources/{ref}
export type AgentSourceView = {
  ref: number
  source_kind: SourceKind
  title: string
  section: string | null
  cited_revision: number
  paragraph_text: string
  highlight: unknown
  changed_since_cited: boolean
}

// E27 POST /api/ai/conversations 요청
export type CreateConversationRequest =
  | { origin: 'note'; note_id: number; note_revision: number; selection: { start: number; end: number } }
  | { origin: 'none' }

// E29 POST /api/ai/conversations/{conversation_id}/turns 요청
export type AskQuestion =
  | { kind: 'free'; text: string }
  | { kind: 'suggested'; text: string; from_turn_id: string }
  | { kind: 'preset'; preset: QuestionPreset }

export type AskReply =
  | { turn_id: string; clarify_option_id: string }
  | { turn_id: string; text: string }
  | { turn_id: string; topic_choice: 'continue' }

export type AskTurnRequest = {
  question: AskQuestion
  add_selections?: { note_id: number; note_revision: number; start: number; end: number }[]
  exclude_selection_ids?: string[]
  reply?: AskReply | null
  retry_of_turn_id?: string | null
}

// 6절 진행 이벤트. result·error가 마지막 이벤트다.
export type StepEventData = { step: AgentStep; state: 'current' | 'done'; paragraph_count?: number; source_kind?: SourceKind }
export type TurnEvent =
  | { type: 'turn'; data: { turn_id: string; seq: number } }
  | { type: 'step'; data: StepEventData }
  | { type: 'delayed' }
  | { type: 'result'; data: AgentTurn }
  | { type: 'error'; data: { code: string; message: string; request_id: string; retry_after_seconds?: number } }
