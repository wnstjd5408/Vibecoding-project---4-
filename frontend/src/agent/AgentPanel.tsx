// CS Agent 'AI에게 질문' 패널(MEG-258, T6c). 화면 목록 2~12번(MEG-239 1단계 결과)의 PC 패널과 모바일 전체 높이 화면이다.
//  - PC(1024px 이상): 오른쪽 480px 패널. 모달이 아니라서 노트를 계속 읽고 고를 수 있다(F6-1~F6-19).
//  - 모바일: 전체 높이 대화 화면(모달). 노트 화면은 뒤에 그대로 있어 닫으면 읽던 위치로 돌아간다(F6-1m~F6-18m).
//  - 대화 상태는 노트 화면(NoteReadPage)이 useAgentConversation으로 가진다. 이 패널은 상태를 그리기만 하고, 닫아도 대화와 초안은 남는다.
//  - 모바일 보드가 없는 상태(지연 안내, 단계 없는 준비 중, 긴 답변의 '새 답변 보기', 다시 넣기 확인, 사용 제한)는 모바일에서 그리지 않는다
//    (2026-11-20 결정 8, MEG-262 디자인 → MEG-263에서 반영).
//  - 예외 상태(MEG-260, T6d): 의미 확인(F6-11·F6-11m), 근거 일부만 확인(F6-12), 근거 없음(F6-12b), 확인된 교정(F6-13·F6-13m),
//    주제 전환 확인(F6-20), 다른 영역 선택(F6-8·F6-8m), 노트 접근 변경(F6-15·F6-15m), 출처만 권한 회수(F6-15b).
//    MEG-262에서 새로 그린 모바일 보드(F6-12m·F6-12bm·F6-15bm·F6-20m)의 상태는 T6g(MEG-263)가 반영한다. 그 전까지 모바일은 질문만 보인다.
//  - 떠 있는 창·전체 화면은 T6f(MEG-261)다.
//  - 다시 답하기 화면과 버튼은 만들지 않는다(MEG-228, spec 부록 A).
import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent, ReactNode } from 'react'
import { Link } from 'react-router'
import { AiBadge, Button } from '../components/index.ts'
import { AiAnswer } from '../notes/AiAnswer.tsx'
import type { AiAnswerFigure } from '../notes/AiAnswer.tsx'
import { NoteBody } from '../notes/NoteBody.tsx'
import { userPaths } from '../routes/paths.ts'
import { canRetry } from './conversation.ts'
import type { AgentConversationController, AgentFailure, AgentState, AskOptions, PendingTurn, StepView } from './conversation.ts'
import { AGENT_MESSAGES as M, PRESETS, questionLabel, questionText, topicLabelOf } from './messages.ts'
import { FRESH_CONTEXT, MAX_QUESTION, agentAccessLost, quoteOf, sectionsOf } from './agentUi.ts'
import type { AgentContextSelection, AgentUi } from './agentUi.ts'
import type {
  AgentFigure,
  AgentQuestion,
  AgentSource,
  AgentTurn,
  AskQuestion,
  ClarifyResult,
  CorrectionResult,
  CreateConversationRequest,
  SourceKind,
} from './types.ts'
import type { OpenSource, SourceState } from './useAgentSource.ts'
import styles from './AgentPanel.module.css'

type AgentPanelProps = {
  open: boolean
  wide: boolean
  state: AgentState
  controller: AgentConversationController
  ui: AgentUi
  onUi: (patch: Partial<AgentUi> | ((ui: AgentUi) => Partial<AgentUi>)) => void
  // 질문이 401 login_required를 받았다(세션 만료). 노트 화면이 패널을 닫고 로그인 안내를 연다.
  onLoginRequired: () => void
  source: OpenSource | null
  sourceState: SourceState | null
  onOpenSource: (turnId: string, ref: number, opener: HTMLElement) => void
  onCloseSource: () => void
  onClose: () => void
  // 패널을 닫을 때 포커스를 돌려줄 곳(노트 본문)
  returnFocus: () => HTMLElement | null
}

type Entry =
  | { kind: 'turn'; key: string; turn: AgentTurn }
  | { kind: 'pending'; key: string; pending: PendingTurn }
  | { kind: 'failure'; key: string; failure: AgentFailure }

const isLimitLike = (failure: AgentFailure | null) => failure !== null && (failure.kind === 'limit_reached' || failure.kind === 'service_unavailable')
// 다시 보낼 수 있는 실패인가(기다릴 시간은 따지지 않는다). 이 실패는 '다시 시도' 전에는 보내기를 잠근다(F6-6p).
const isRetryable = (failure: AgentFailure | null) => failure !== null && canRetry(failure, Number.POSITIVE_INFINITY)


// 서버 그림(AgentFigure)을 AiAnswer의 모양으로 맞춘다. 객체가 아닌 항목은 AiAnswer가 걸러 낸다.
function figuresOf(figures: AgentFigure[] | undefined): AiAnswerFigure[] {
  return (figures ?? []).map((figure, index) =>
    typeof figure === 'object' && figure !== null
      ? { ...figure, figure_id: figure.figure_id ?? `f-${index + 1}`, kind: figure.kind ?? '' }
      : (figure as unknown as AiAnswerFigure),
  )
}

// 확인 카드에 답할 때 다시 보낼 질문. 가린 추천 질문처럼 글이 없으면 null이다.
// 빠른 질문은 칩 종류로, 그 밖은 직접 입력으로 보낸다(주제 전환 '이 대화에서 계속'은 free와 같은 글이어야 한다. spec E29).
function askOf(question: AgentQuestion): AskQuestion | null {
  if (question.kind === 'preset' && question.preset) return { kind: 'preset', preset: question.preset }
  return question.text ? { kind: 'free', text: question.text } : null
}

// 선택 칩 하나(입력 칸 위). 대화 전에는 고른 문장, 대화 중에는 대화의 선택 문맥과 '현재 대화에 추가'로 고른 문장이다.
type Chip = { key: string; text: string; exclude: (ui: AgentUi) => Partial<AgentUi> }

function chipsOf(state: AgentState, ui: AgentUi): Chip[] {
  const conversation = state.conversation
  if (!conversation) return ui.selection && !ui.excluded ? [{ key: 'selection', text: ui.selection.text, exclude: () => ({ excluded: true }) }] : []
  const context: Chip[] = conversation.context_selections
    .filter((item) => !ui.excludedIds.includes(item.selection_id))
    .map((item) => ({ key: item.selection_id, text: item.text_preview, exclude: (current) => ({ excludedIds: [...current.excludedIds, item.selection_id] }) }))
  const added: Chip[] = ui.added.map((item) => ({
    key: `added-${item.start}-${item.end}`,
    text: item.text,
    exclude: (current) => ({ added: current.added.filter((other) => other !== item) }),
  }))
  return [...context, ...added]
}

const sameRange = (a: AgentContextSelection, b: AgentContextSelection) => a.noteId === b.noteId && a.start === b.start && a.end === b.end

// 가린 턴 가운데 처음 영향받은 턴(가림 연쇄의 첫 턴). 다시 묻기는 이 턴에만 둔다(결정 15).
function firstHiddenIds(turns: AgentTurn[]): Set<string> {
  const ids = new Set<string>()
  turns.forEach((turn, index) => {
    if (!turn.hidden) return
    if (index === 0 || !turns[index - 1].hidden || turn.hidden.retry_allowed) ids.add(turn.turn_id)
  })
  return ids
}

export function AgentPanel(props: AgentPanelProps) {
  const { open, wide, state, controller, ui, onUi, source, onClose, onCloseSource, returnFocus } = props
  const dialogRef = useRef<HTMLDialogElement>(null)
  const titleRef = useRef<HTMLHeadingElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const inputId = useId()
  const selectionId = useId()
  const [showSelection, setShowSelection] = useState(false)
  const latest = useRef({ onClose, onCloseSource, source, returnFocus })
  useEffect(() => {
    latest.current = { onClose, onCloseSource, source, returnFocus }
  })

  // 열고 닫기. PC는 모달이 아닌 dialog(show), 모바일은 모달(showModal)이다. 폭이 바뀌면 같은 dialog를 다시 연다(내용은 그대로).
  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (!open) {
      if (!dialog.open) return
      const active = document.activeElement
      const holder = active instanceof HTMLElement ? active.closest('dialog') : null
      dialog.close()
      // 다른 패널이 막 열려 포커스를 가져갔으면(용어 패널 등) 빼앗지 않는다.
      if (holder !== null && holder !== dialog) return
      const target = latest.current.returnFocus()
      if (target?.isConnected) target.focus({ preventScroll: true })
      return
    }
    const modal = !wide
    if (dialog.open && dialog.matches(':modal') === modal) return
    const first = !dialog.open
    // 폭이 바뀌어 다시 열 때는 패널 안에서 포커스가 있던 곳(입력 칸 등)을 기억했다가 되돌린다. close()가 포커스를 패널 밖으로 옮기기 때문이다.
    const focused = !first && document.activeElement instanceof HTMLElement && dialog.contains(document.activeElement) ? document.activeElement : null
    if (dialog.open) dialog.close()
    if (modal) dialog.showModal()
    else dialog.show()
    // 닫혀 있는 동안에는 높이를 잴 수 없으므로 연 뒤에 입력 칸 높이를 다시 맞춘다.
    resizeInput(inputRef.current)
    if (first) titleRef.current?.focus({ preventScroll: true })
    else focused?.focus({ preventScroll: true })
  }, [open, wide])

  // Esc: 출처 보기면 대화로 돌아가고, 아니면 패널을 닫는다. 모달(모바일)은 cancel 이벤트로, PC는 문서의 keydown으로 듣는다.
  const onEscape = () => {
    if (latest.current.source) latest.current.onCloseSource()
    else latest.current.onClose()
  }
  useEffect(() => {
    if (!open || !wide) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented || event.isComposing) return
      // 위에 모달(로그인 안내 시트 등)이 열려 있으면 그쪽이 Esc를 맡는다.
      if (document.querySelector('dialog:modal')) return
      onEscape()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, wide])

  const failure = state.failure
  const limitLike = isLimitLike(failure)
  const accessLost = agentAccessLost(state)

  // 출처가 404(gone)면 출처 보기를 닫고 대화를 다시 읽는다. 출처만 회수됐으면 가린 턴(F6-15b)이, 노트까지 막혔으면 접근 변경(F6-15)이 보인다.
  const sourceStatus = props.sourceState?.status
  useEffect(() => {
    if (sourceStatus !== 'gone') return
    latest.current.onCloseSource()
    void controller.refresh()
  }, [sourceStatus, controller])
  // 노트 접근이 바뀌면 출처도 함께 닫는다(결정 3).
  useEffect(() => {
    if (accessLost && latest.current.source) latest.current.onCloseSource()
  }, [accessLost])

  // 출처 보기로 바꿀 때 대화 스크롤 위치를 기억했다가 돌아오면 되살린다(9절 '복귀 시 답변 스크롤과 질문 초안을 복원').
  const savedScroll = useRef(0)
  const sourceOpen = source !== null
  useLayoutEffect(() => {
    const body = bodyRef.current
    if (!body) return
    if (sourceOpen) return
    body.scrollTop = savedScroll.current
  }, [sourceOpen])
  const openSource = (turnId: string, ref: number, opener: HTMLElement) => {
    savedScroll.current = bodyRef.current?.scrollTop ?? 0
    props.onOpenSource(turnId, ref, opener)
  }

  const conversation = state.conversation
  const pending = state.pending
  const chips = chipsOf(state, ui)
  const selectionText = chips.length > 0 ? chips.map((chip) => chip.text).join('\n') : null
  const hasSelection = chips.length > 0
  const topic = conversation?.topic_label || (ui.selection && !ui.excluded ? topicLabelOf(ui.selection.text) : '')
  const fresh = state.turns.length === 0 && pending === null && failure === null

  const entries: Entry[] = state.turns.map((turn) => ({ kind: 'turn', key: turn.turn_id, turn }))
  if (pending) entries.push({ kind: 'pending', key: 'pending', pending })
  // 모바일 사용 제한 보드가 없어(결정 8) 모바일에서는 사용 제한을 대화 항목으로 넣지 않는다. 넣으면 빈 항목이 앞 답변을 가린다.
  else if (failure?.question && !(limitLike && !wide)) entries.push({ kind: 'failure', key: 'failure', failure })
  const lastEntry = entries.at(-1)
  const latestTurn = lastEntry?.kind === 'turn' && !lastEntry.turn.hidden ? lastEntry.turn : null
  const latestState = latestTurn?.status === 'completed' ? latestTurn.result?.state : undefined
  // 대화 중에 노트에서 새로 고른 문장(F6-8). 대화를 시작하기 전이면 노트 화면이 선택 문맥으로 바로 넣는다.
  const candidate = fresh ? null : ui.candidate
  // 주제 전환 확인 카드(F6-20). 모바일 보드(F6-20m)는 T6g(MEG-263)에서 반영한다.
  const topicCheck = wide && latestState === 'topic_check'

  // 보내기 잠금: 생성 중, 다시 시도 전의 요청 실패(F6-6p), 다시 확인 전의 사용 제한(F6-17, 모바일 보드 없음),
  // 고르기 전의 확인 카드(주제 전환 F6-20 결정 38, 다른 영역 선택 F6-8)
  const failureLock = failure !== null && (limitLike ? wide : isRetryable(failure))
  const choiceLock = topicCheck || candidate !== null
  const locked = pending !== null || failureLock || choiceLock

  const firstHidden = firstHiddenIds(state.turns)
  // 접어도 보여 줄 첫 항목. 보통은 마지막 항목이고, 출처 회수로 가린 턴이 있으면 처음 영향받은 턴부터 보인다(F6-15b).
  // 다시 묻기를 쓸 수 있거나 그 뒤가 모두 가린 턴인 연쇄만 본다. 다시 묻기로 끝난 옛 연쇄까지 펼치지 않는다.
  const hiddenStart = entries.findLastIndex((entry, index) =>
    entry.kind === 'turn' && firstHidden.has(entry.turn.turn_id)
    && (entry.turn.hidden?.retry_allowed === true || entries.slice(index + 1).every((rest) => rest.kind === 'turn' && rest.turn.hidden)))
  const keepFrom = candidate ? entries.length : hiddenStart >= 0 ? hiddenStart : Math.max(entries.length - 1, 0)
  const collapsed = !ui.expanded && keepFrom > 0
  // 다른 영역 선택 카드가 있으면 앞 대화는 '이전 대화 보기' 뒤로 접고 카드만 보인다(F6-8).
  const shown = collapsed ? entries.slice(keepFrom) : entries
  const lastKey = candidate ? 'candidate' : (lastEntry?.key ?? null)
  // 가린 턴이 새로 보이면(E28 다시 읽기 등) 처음 영향받은 턴의 질문부터 보이게 위로 옮긴다. 앞 답변을 읽던 위치에 남으면 안내 위가 잘린다.
  const hiddenKey = hiddenStart >= 0 ? entries[hiddenStart].key : null
  useLayoutEffect(() => {
    const body = bodyRef.current
    if (hiddenKey === null || !body) return
    const first = body.querySelector<HTMLElement>('[data-entry]')
    body.scrollTop = first ? Math.max(0, first.offsetTop - body.offsetTop) : 0
  }, [hiddenKey])

  // 긴 대화(F6-10): 맨 아래를 보고 있을 때만 새 내용을 따라간다. 위에서 읽고 있으면 옮기지 않고 '새 답변 보기'를 띄운다(PC만).
  const [atBottom, setAtBottom] = useState(true)
  const [unseen, setUnseen] = useState(false)
  const bottomRef = useRef(true)
  const previousKey = useRef(lastKey)
  const scrollToLatest = () => {
    const body = bodyRef.current
    const last = body?.querySelector<HTMLElement>('[data-entry]:last-of-type')
    if (body && last) body.scrollTop = Math.max(0, last.offsetTop - body.offsetTop)
  }
  const onScroll = () => {
    const body = bodyRef.current
    if (!body) return
    const bottom = body.scrollHeight - body.scrollTop - body.clientHeight < 24
    bottomRef.current = bottom
    setAtBottom(bottom)
    if (bottom) setUnseen(false)
  }
  useLayoutEffect(() => {
    if (previousKey.current === lastKey) return
    previousKey.current = lastKey
    // 질문을 보낸 직후(pending)이거나 맨 아래를 보고 있었으면 새 항목의 시작으로 옮긴다. 답변은 한 번에 오므로 끝이 아니라 시작을 보여 준다.
    if (lastKey !== null && lastKey !== 'pending' && !bottomRef.current) setUnseen(true)
    else if (lastKey !== null) scrollToLatest()
    // 내용이 줄어 스크롤 이벤트 없이 맨 아래가 된 경우(새 대화 등)에도 위치를 다시 잰다.
    onScroll()
  }, [lastKey])
  const showNewAnswer = wide && !sourceOpen && !atBottom && (unseen || (pending !== null && !collapsed))

  // --- 동작 ---

  const contextFor = (): CreateConversationRequest | undefined => {
    if (conversation) return undefined
    if (ui.selection && !ui.excluded) {
      const { noteId, revision, start, end } = ui.selection
      return { origin: 'note', note_id: noteId, note_revision: revision, selection: { start, end } }
    }
    return { origin: 'none' }
  }
  // 질문 하나가 끝난 뒤(성공·실패 모두). 로그인이 끊겼으면 노트 화면에 알리고,
  // 사용 제한(S12)이면 보내려던 질문 글을 비어 있는 입력 칸에 되돌려 놓는다(F6-17 '쓰던 내용은 아래 칸에 남겨 두었어요').
  // 세션이 끊긴 경우(401)도 질문 글을 비어 있는 입력 칸에 남긴다. 로그인 뒤 다시 열면 이어서 보낼 수 있다.
  const afterRun = () => {
    const ended = controller.getSnapshot().failure
    const login = ended?.kind === 'login_required'
    if ((login || isLimitLike(ended)) && ended?.question && ended.question.kind !== 'preset') {
      const restore = ended.question.text ?? ''
      onUi((current) => (current.draft.trim() === '' ? { draft: restore } : {}))
    }
    if (login) {
      controller.dismissFailure()
      props.onLoginRequired()
    }
  }
  const focusInput = () => inputRef.current?.focus({ preventScroll: true })
  // 다음 질문의 선택 문맥 변경: 제외한 문맥(exclude_selection_ids)과 '현재 대화에 추가'로 고른 문장(add_selections)
  const contextChanges = (): Pick<AskOptions, 'exclude_selection_ids' | 'add_selections'> => {
    if (!conversation) return {}
    const known = new Set(conversation.context_selections.map((item) => item.selection_id))
    const excludes = ui.excludedIds.filter((id) => known.has(id))
    const adds = ui.added.map((item) => ({ note_id: item.noteId, note_revision: item.revision, start: item.start, end: item.end }))
    return { ...(excludes.length > 0 ? { exclude_selection_ids: excludes } : {}), ...(adds.length > 0 ? { add_selections: adds } : {}) }
  }
  // 누른 버튼(빠른 질문, 추천 질문, 다시 시도, 중단, 확인 카드)은 누른 뒤 사라지므로 포커스를 입력 칸으로 옮긴다.
  // 확인 카드의 선택(주제 전환·의미 확인)은 카드가 보내기를 잠근 동안에도 보낸다(force).
  const ask = (question: AskQuestion, extra: Pick<AskOptions, 'reply'> = {}, force = false) => {
    if (pending || (locked && !force)) return
    if (source) onCloseSource()
    const sentAdded = ui.added
    controller.ask(question, { context: contextFor(), ...contextChanges(), ...extra }).then(() => {
      afterRun()
      // 추가한 문장이 대화의 선택 문맥이 됐다. 칩을 서버의 선택 문맥으로 바꾼다(E28).
      if (sentAdded.length > 0 && controller.getSnapshot().failure === null) {
        onUi((current) => ({ added: current.added.filter((item) => !sentAdded.includes(item)) }))
        void controller.refresh()
      }
    }, () => {})
    focusInput()
  }
  const retry = () => {
    void controller.retry().then(afterRun)
    focusInput()
  }
  // '같은 질문 다시 하기'(F6-15b). 질문 없이 retry_of_turn_id만 보낸다(MEG-257).
  const askAgain = (turn: AgentTurn) => {
    if (locked) return
    void controller.askAgain(turn).then(afterRun)
    focusInput()
  }
  // 주제 전환 확인(F6-20, 결정 40): '새 대화로 질문'은 앞 대화와 선택한 문장을 모두 빼고 이 질문만으로 새 대화를 시작한다.
  const askInNewConversation = (question: AskQuestion) => {
    if (pending) return
    controller.reset()
    onUi({ ...FRESH_CONTEXT, selection: null })
    setUnseen(false)
    controller.ask(question, { context: { origin: 'none' } }).then(afterRun, () => {})
    focusInput()
  }
  // 다른 영역 선택(F6-8, 결정 20)
  const addCandidate = () => {
    onUi((current) => {
      const next = current.candidate
      if (!next) return {}
      return { candidate: null, added: current.added.some((item) => sameRange(item, next)) ? current.added : [...current.added, next] }
    })
    focusInput()
  }
  const newWithCandidate = () => {
    if (pending || !ui.candidate) return // 생성 중에는 새 대화를 잠근다(결정 11)
    controller.reset()
    onUi({ ...FRESH_CONTEXT, selection: ui.candidate })
    setUnseen(false)
    titleRef.current?.focus({ preventScroll: true })
  }
  // 의미 확인(F6-11)이 마지막 턴이면 입력 칸의 글은 직접 보충(reply.text)으로 보낸다.
  const clarifyTurn = latestState === 'clarify' ? latestTurn : null
  const text = ui.draft.trim()
  const canSend = !locked && text !== '' && [...text].length <= MAX_QUESTION
  const send = () => {
    if (!canSend) return
    ask({ kind: 'free', text }, clarifyTurn ? { reply: { turn_id: clarifyTurn.turn_id, text } } : {})
    onUi({ draft: '' })
  }
  const onKeyDown = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    // PC는 Enter로 보내고 Shift+Enter로 줄을 바꾼다. 모바일은 보내기 버튼만 쓴다(10절).
    // 보낼 수 없는 동안(생성 중, 다시 시도·다시 확인 전)에는 Enter를 막지 않아 초안에 줄을 바꿀 수 있다.
    if (!wide || locked || event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return
    event.preventDefault()
    send()
  }
  const newConversation = () => {
    if (pending) return // 생성 중에는 잠근다(2026-11-20 결정 11). 먼저 중단하면 다시 열린다.
    controller.reset()
    onUi(FRESH_CONTEXT)
    setUnseen(false)
    titleRef.current?.focus({ preventScroll: true })
  }
  const expand = () => {
    onUi({ expanded: true })
    void controller.refresh()
  }
  useLayoutEffect(() => resizeInput(inputRef.current), [ui.draft, open, wide])

  const label = sourceOpen || pending ? M.labelKeep
    : failureLock ? (limitLike ? M.labelLockedLimit : M.labelLockedFailed)
    : state.cancelled ? M.labelKeepStopped
    : fresh ? M.labelFirst
    : candidate ? M.labelNext
    : latestState === 'clarify' ? M.labelClarify
    // 근거 일부·근거 없음의 모바일 보드(F6-12m·F6-12bm)는 T6g(MEG-263)에서 반영한다.
    : wide && latestState === 'partial' ? M.labelPartial
    : wide && latestState === 'no_evidence' ? M.labelNoEvidence
    : M.labelNext

  const header = wide
    ? <div className={styles.head}>
        <h2 id={titleId} ref={titleRef} tabIndex={-1} className={styles.title}>{source ? M.sourceTitle(source.ref) : M.title}</h2>
        <div className={styles.headActions}>
          {source
            ? <button type="button" className={styles.iconButton} aria-label={M.backToConversation} onClick={onCloseSource}><BackIcon /></button>
            : <>
                <button type="button" className={styles.headButton} aria-disabled={pending ? true : undefined} onClick={newConversation}>{M.newConversation}</button>
                <button type="button" className={`${styles.headButton} ${styles.closeButton}`} onClick={onClose}>{M.close}</button>
              </>}
        </div>
      </div>
    : <div className={styles.mobileHead}>
        {source
          ? <>
              <button type="button" className={styles.iconButton} aria-label={M.backToConversation} onClick={onCloseSource}><BackIcon /></button>
              <h1 id={titleId} ref={titleRef} tabIndex={-1} className={`${styles.title} ${styles.mobileSourceTitle}`}>{M.sourceTitle(source.ref)}</h1>
            </>
          : <>
              <button type="button" className={styles.textButton} onClick={onClose}>{M.backToNote}</button>
              <h1 id={titleId} ref={titleRef} tabIndex={-1} className={`${styles.title} ${styles.mobileTitle}`}>{M.title}</h1>
            </>}
      </div>

  const context = source ? null
    : <div className={wide ? styles.context : styles.mobileContext}>
        {topic ? <div className={styles.topic}>{M.topic(topic)}</div> : null}
        {wide && (conversation ? conversation.origin === 'note' : ui.selection !== null) ? <div className={styles.muted}>{hasSelection ? M.contextWithSelection : M.contextNoteOnly}</div> : null}
        {hasSelection
          ? <button type="button" className={styles.underline} aria-expanded={showSelection} aria-controls={selectionId} onClick={() => setShowSelection((value) => !value)}>{M.showSelection}</button>
          : null}
        {hasSelection && showSelection ? <div id={selectionId} role="region" aria-label={M.selectionRegion} className={styles.selectionFull}>{selectionText}</div> : null}
      </div>

  const sourceTurn = source ? state.turns.find((turn) => turn.turn_id === source.turnId) : undefined

  if (accessLost) {
    // S9 노트 접근 변경(F6-15·F6-15m, 결정 3): 대화와 출처를 닫고 노트 목록으로 가는 길만 둔다. PC 노트 자리는 노트 화면이 같은 안내로 바꾼다.
    return (
      <dialog ref={dialogRef} className={wide ? styles.panel : styles.full} aria-labelledby={titleId}
        onCancel={(event) => { event.preventDefault(); onEscape() }}>
        {wide
          ? <div className={styles.head}>
              <h2 id={titleId} ref={titleRef} tabIndex={-1} className={styles.title}>{M.title}</h2>
              <div className={styles.headActions}>
                <Link to={userPaths.noteList} className={`${styles.headButton} ${styles.closeButton}`}>{M.close}</Link>
              </div>
            </div>
          : <div className={styles.mobileHead}>
              <Link to={userPaths.noteList} className={styles.textButton}>{M.accessList}</Link>
              <h1 id={titleId} ref={titleRef} tabIndex={-1} className={`${styles.title} ${styles.mobileTitle}`}>{M.title}</h1>
            </div>}
        <div className={wide ? styles.body : styles.mobileBody}>
          <div role="status" className={wide ? styles.statusBox : styles.accessBox}>
            {wide
              ? <p className={styles.noticeTitleSmall}>{M.accessClosed}</p>
              : <>
                  <h2 className={styles.accessTitle}>{M.accessTitle}</h2>
                  <p className={styles.noticeText}>{M.accessClosed}</p>
                  <p className={styles.noticeText}>{M.accessHelp}</p>
                  <Link to={userPaths.noteList} className={styles.primaryLink}>{M.accessToList}</Link>
                </>}
          </div>
        </div>
      </dialog>
    )
  }

  return (
    <dialog ref={dialogRef} className={wide ? styles.panel : styles.full} aria-labelledby={titleId}
      onCancel={(event) => { event.preventDefault(); onEscape() }}>
      {header}
      {context}
      {source
        ? <div className={wide ? styles.sourceBody : styles.mobileBody}>
            {wide
              ? <SourcePanelInfo state={props.sourceState} quote={quoteOf(sourceTurn, source.ref)} question={sourceTurn ? questionText(sourceTurn.question) : ''} />
              : <SourceMobile state={props.sourceState} source={source} />}
          </div>
        : null}
      <div ref={bodyRef} className={wide ? styles.body : styles.mobileBody} hidden={sourceOpen} onScroll={onScroll}
        {...(wide && ui.expanded && entries.length > 1 ? { role: 'log', 'aria-label': M.log, tabIndex: 0 } : {})}>
        {fresh
          ? <AskIntro disabled={!hasSelection} onPreset={(preset) => ask({ kind: 'preset', preset })} />
          : <>
              {collapsed
                ? <button type="button" className={styles.previous} onClick={expand}>{M.previous(conversation?.topic_label ?? topic, questionLabel(entryQuestion(entries[0])))}</button>
                : null}
              {state.loadFailure && !collapsed ? <p role="alert" className={styles.smallError}>{M.previousFailed}</p> : null}
              {shown.map((entry) => <div key={entry.key} data-entry="" className={styles.entry}>
                <EntryView entry={entry} latest={entry.key === lastKey} wide={wide} state={state} controller={controller}
                  hasSelection={hasSelection} locked={locked} draft={ui.draft} onRetry={retry}
                  onDraft={(draft) => { onUi({ draft }); focusInput() }} onAsk={ask} onSource={openSource} onClose={onClose} onFocusInput={focusInput}
                  firstHidden={entry.kind === 'turn' && firstHidden.has(entry.turn.turn_id)} onAskAgain={askAgain}
                  onNewConversationAsk={askInNewConversation} />
              </div>)}
              {candidate
                ? <div data-entry="" className={styles.entry}>
                    <CandidateCard candidate={candidate} newLocked={pending !== null} onAdd={addCandidate} onNew={newWithCandidate} wide={wide} />
                  </div>
                : null}
            </>}
      </div>
      {showNewAnswer
        ? <div className={styles.newAnswerBar}>
            <button type="button" className={styles.newAnswer} onClick={() => { scrollToLatest(); setUnseen(false) }}>{M.newAnswer}</button>
          </div>
        : null}
      <div className={wide ? styles.composerArea : styles.mobileComposerArea}>
        {hasSelection && !(source && !wide)
          ? chips.map((chip) => <div key={chip.key} className={styles.chip}>
              <span className={styles.chipText}>{M.selectionChip(chip.text)}</span>
              <div className={styles.chipActions}>
                {wide ? <button type="button" className={styles.chipButton} aria-expanded={showSelection} aria-controls={selectionId} onClick={() => setShowSelection((value) => !value)}>{M.selectionFull}</button> : null}
                <button type="button" className={styles.chipButton} onClick={() => { onUi(chip.exclude); setShowSelection(false) }}>{M.exclude}</button>
              </div>
            </div>)
          : null}
        <label htmlFor={inputId} className={styles.label}>{label}</label>
        <div className={styles.composer}>
          <textarea id={inputId} ref={inputRef} rows={2} className={styles.input} value={ui.draft} maxLength={MAX_QUESTION * 2}
            placeholder={fresh ? M.placeholderFirst : M.placeholderNext}
            onChange={(event) => onUi({ draft: event.target.value })} onKeyDown={onKeyDown} />
          {pending
            ? <button type="button" className={styles.stop} aria-label={M.stop} aria-disabled={pending.cancelRequested ? true : undefined}
                onClick={() => { if (!pending.cancelRequested) { void controller.cancel(); focusInput() } }}><StopIcon /></button>
            : null}
          <button type="button" className={styles.send} aria-label={M.send} aria-disabled={canSend ? undefined : true} onClick={send}><SendIcon /></button>
        </div>
      </div>
    </dialog>
  )
}

// 입력 칸은 약 4줄까지 늘어난 뒤 칸 안에서 스크롤한다(14.2). 보이지 않는 동안(높이 0)에는 기본 높이(2줄)로 둔다.
function resizeInput(input: HTMLTextAreaElement | null) {
  if (!input) return
  input.style.height = 'auto'
  const height = input.scrollHeight
  input.style.height = height > 0 ? `${Math.min(height, 24 * 4 + 16)}px` : ''
}

function entryQuestion(entry: Entry | undefined): Pick<AgentQuestion, 'kind' | 'text' | 'preset'> {
  if (!entry) return { kind: 'free', text: '' }
  if (entry.kind === 'turn') return entry.turn.question
  if (entry.kind === 'pending') return entry.pending.question
  return entry.failure.question ?? { kind: 'free', text: '' }
}

// F6-1 질문 준비: 빠른 질문 칩 3개(결정 23). 선택 문장을 제외하면 칩을 잠근다(14.5 AI 제안).
function AskIntro({ disabled, onPreset }: { disabled: boolean; onPreset: (preset: AgentQuestion['preset'] & string) => void }) {
  return <>
    <p className={styles.intro}>{disabled ? M.askIntroNoSelection : M.askIntro}</p>
    <div role="group" aria-label={M.quickGroup} className={styles.quick}>
      {PRESETS.map((item, index) => <button key={item.preset} type="button" className={index === 0 ? `${styles.quickChip} ${styles.quickPrimary}` : styles.quickChip}
        aria-disabled={disabled ? true : undefined} onClick={() => { if (!disabled) onPreset(item.preset) }}>{item.label}</button>)}
    </div>
    <p className={styles.hint}>{M.quickHint}</p>
  </>
}

type EntryProps = {
  entry: Entry
  latest: boolean
  wide: boolean
  state: AgentState
  controller: AgentConversationController
  hasSelection: boolean
  locked: boolean
  draft: string
  onRetry: () => void
  onDraft: (draft: string) => void
  onAsk: (question: AskQuestion, extra?: Pick<AskOptions, 'reply'>, force?: boolean) => void
  onSource: (turnId: string, ref: number, opener: HTMLElement) => void
  onClose: () => void
  onFocusInput: () => void
  // 가림 연쇄의 첫 턴인가(F6-15b). '같은 질문 다시 하기'와 가림 안내는 이 턴에 둔다.
  firstHidden: boolean
  onAskAgain: (turn: AgentTurn) => void
  onNewConversationAsk: (question: AskQuestion) => void
}

function Question({ question }: { question: Pick<AgentQuestion, 'kind' | 'text' | 'preset'> }) {
  const text = questionText(question)
  if (text === '') return null
  return <>
    <div className={styles.caption}>{M.question}</div>
    <p className={styles.question}>{text}</p>
  </>
}

function EntryView(props: EntryProps) {
  const { entry } = props
  if (entry.kind === 'pending') return <PendingView pending={entry.pending} wide={props.wide} hasSelection={props.hasSelection} />
  if (entry.kind === 'failure') return <FailureView {...props} failure={entry.failure} />
  return <TurnView {...props} turn={entry.turn} />
}

// S2 준비 중(F6-2)과 AI 추론 단계(F6-2b·F6-2bm), 응답 지연(F6-19). 끊긴 뒤 E30으로 결과를 받는 동안도 같은 화면이다(화면 목록 5번).
function PendingView({ pending, wide, hasSelection }: { pending: PendingTurn; wide: boolean; hasSelection: boolean }) {
  const badgeId = useId()
  const stepsId = useId()
  const steps = pending.steps
  const current = steps.find((step) => step.state === 'current') ?? null
  const delayed = wide && pending.delayed
  return <>
    <Question question={pending.question} />
    {wide && steps.length === 0
      ? <>
          <span id={badgeId}><AiBadge>{M.aiBadge}</AiBadge></span>
          <div role="group" aria-labelledby={badgeId} className={styles.aiBox}>
            <p role="status" className={styles.preparing}>{M.preparing}</p>
          </div>
        </>
      : <div className={styles.stepsBox}>
          <p id={stepsId} className={styles.stepsTitle}>{M.stepsTitle}</p>
          <ol aria-labelledby={stepsId} className={styles.steps}>
            {steps.map((step) => <li key={step.step} aria-current={step.state === 'current' ? 'step' : undefined} className={styles.step}>
              {step.state === 'done' ? <DoneIcon /> : <CurrentIcon />}
              <div>
                <div className={step.state === 'current' ? styles.stepNameCurrent : styles.stepName}>{M.stepName(step.step, step.sourceKind)}</div>
                <div className={styles.stepDetail}>{stepDetail(step, hasSelection)}</div>
              </div>
            </li>)}
          </ol>
          {/* 단계가 바뀔 때만 읽도록 목록 밖에 알림 영역 하나를 둔다(14.5 AI 제안). */}
          <p role="status" className={styles.srOnly}>{current ? M.stepNow(M.stepName(current.step, current.sourceKind), delayed) : ''}</p>
        </div>}
    {delayed
      ? <div className={styles.noticeBox}>
          <p className={styles.noticeTitleSmall}>{M.delayedTitle}</p>
          <p className={styles.noticeText}>{M.delayedHelp}</p>
        </div>
      : null}
  </>
}

function stepDetail(step: StepView, hasSelection: boolean): string {
  if (step.state === 'current') return M.stepCurrent
  if (step.step === 'understand') return M.stepUnderstood(hasSelection)
  if (step.step === 'retrieve') return M.stepRetrieved(step.paragraphCount, step.sourceKind)
  return M.stepDone
}

// S8 요청 실패(F6-6p·F6-6)와 S12 사용 제한(F6-17). 질문은 남기고, 쓰던 초안은 입력 칸에 그대로 둔다(AC-3).
function FailureView({ failure, wide, controller, draft, onRetry, onClose, onFocusInput }: EntryProps & { failure: AgentFailure }) {
  if (isLimitLike(failure)) {
    // 질문 글을 입력 칸에 되돌려 놓았으면 질문 줄은 다시 보이지 않는다(F6-17).
    const inDraft = failure.question !== null && draft.trim() !== '' && draft.trim() === questionText(failure.question).trim()
    return <>
      {inDraft ? null : <Question question={failure.question ?? { kind: 'free' }} />}
      {wide
        ? <div role="alert" className={styles.alertBox}>
            <p className={styles.noticeTitle}>{M.limited}</p>
            <p className={styles.noticeText}>{M.limitedHelp}</p>
            <div className={styles.actions}>
              <Button variant="primary" onClick={() => { controller.dismissFailure(); onFocusInput() }}>{M.recheck}</Button>
              <Button onClick={onClose}>{M.keepReading}</Button>
            </div>
          </div>
        : null}
    </>
  }
  const retryable = isRetryable(failure)
  return <>
    <Question question={failure.question ?? { kind: 'free' }} />
    <div role="alert" className={styles.alertBox}>
      <p className={styles.noticeTitle}>{M.failed}</p>
      {retryable
        ? <>
            <p className={styles.noticeText}>{M.failedHelp}</p>
            <div className={styles.actions}>
              <Button variant="primary" aria-disabled={canRetry(failure) ? undefined : true} onClick={onRetry}>{M.retry}</Button>
            </div>
          </>
        : null}
    </div>
    <button type="button" className={styles.linkButton} onClick={onClose}>{M.backToNote}</button>
  </>
}

function TurnView(props: EntryProps & { turn: AgentTurn }) {
  const { turn, latest, locked, wide, onAsk, onSource, onClose } = props
  const badgeId = useId()
  if (turn.status === 'cancelled') return <StoppedView {...props} />
  // 가린 턴은 답변·출처·추천 질문을 그리지 않는다(AC-2). 서버도 result를 빼고 보낸다. 모바일 보드(F6-15bm)는 T6g(MEG-263)다.
  if (turn.hidden) return <HiddenView {...props} />
  const state = turn.status === 'completed' ? turn.result?.state : undefined
  if (state === 'clarify') return <ClarifyView {...props} result={turn.result as ClarifyResult} />
  // 근거 없음(F6-12b)과 주제 전환 확인(F6-20)의 모바일 보드는 T6g(MEG-263)에서 반영한다. 그 전까지 모바일은 질문만 보인다.
  if (state === 'no_evidence') return wide ? <NoEvidenceView {...props} /> : <Question question={turn.question} />
  if (state === 'topic_check') return wide ? <TopicCheckView {...props} /> : <Question question={turn.question} />
  const result = sectionsOf(turn.result)
  const sources: AgentSource[] = result?.sources ?? []
  const suggestions = latest && result ? (result.suggestions ?? []).slice(0, 3) : []
  const openRef = (ref: number, button: HTMLElement) => onSource(turn.turn_id, ref, button)
  return <>
    <Question question={turn.question} />
    {result
      ? <>
          <span id={badgeId}><AiBadge>{M.aiBadge}</AiBadge></span>
          <div role="group" aria-labelledby={badgeId} className={styles.aiBox}>
            <AiAnswer sections={result.sections} figures={figuresOf(result.figures)} sources={sources} onSource={openRef} />
            {result.state === 'correction' ? <CorrectionParts result={result} sources={sources} onSource={openRef} /> : null}
            {/* 근거 일부만 확인(F6-12). 한계 문장에는 인용을 붙이지 않는다. 모바일 보드(F6-12m)는 T6g(MEG-263)다. */}
            {result.state === 'partial' && wide && result.limitation
              ? <>
                  <h3 className={styles.partHeading}>{M.partialUnconfirmed}</h3>
                  <p className={styles.partText}>{result.limitation}</p>
                </>
              : null}
          </div>
          {sources.length > 0
            ? <div className={styles.references}>
                <div className={styles.caption}>{M.references}</div>
                {sources.map((item) => <button key={item.ref} type="button" className={styles.reference}
                  onClick={(event) => onSource(turn.turn_id, item.ref, event.currentTarget)}>{M.referenceLabel(item.ref, item.source_kind, item.title, item.section)}</button>)}
              </div>
            : null}
          {suggestions.length > 0
            ? <>
                <div className={styles.caption}>{M.suggestions}</div>
                <div className={styles.suggestions}>
                  {suggestions.map((text) => <button key={text} type="button" className={styles.suggestion} aria-disabled={locked ? true : undefined}
                    onClick={() => { if (!locked) onAsk({ kind: 'suggested', text, from_turn_id: turn.turn_id }) }}>{text}</button>)}
                </div>
              </>
            : null}
          {result.state === 'partial' && wide && latest ? <button type="button" className={styles.linkButton} onClick={onClose}>{M.backToNote}</button> : null}
        </>
      : null}
  </>
}

// S6 확인된 교정(F6-13·F6-13m): 노트에서 확인할 부분(노트 문장 → 근거 문단 기준), 확인하지 못한 부분. 노트는 고치지 않는다.
function CorrectionParts({ result, sources, onSource }: { result: CorrectionResult; sources: AgentSource[]; onSource: (ref: number, button: HTMLElement) => void }) {
  const kindOf = (refs: number[]): SourceKind => sources.find((item) => refs.includes(item.ref))?.source_kind ?? 'note'
  const unresolved = result.unresolved ?? []
  return <>
    {result.corrections.length > 0
      ? <>
          <h3 className={styles.partHeading}>{M.correctionTitle}</h3>
          {result.corrections.map((item, index) => <div key={index} className={styles.correction}>
            <div className={styles.caption}>{M.correctionNote}</div>
            <p className={styles.partText}>{M.quoted(item.note_excerpt)}</p>
            <div className={styles.caption}>{M.correctionBasis(kindOf(item.source_refs))}</div>
            <AiAnswer sections={[{ body: item.corrected }]} sources={sources} onSource={onSource} />
          </div>)}
        </>
      : null}
    {unresolved.length > 0
      ? <>
          <h3 className={styles.partHeading}>{M.correctionUnresolved}</h3>
          {unresolved.map((text, index) => <p key={index} className={styles.partText}>{text}</p>)}
        </>
      : null}
    <p className={styles.hintSmall}>{M.correctionNoEdit}</p>
  </>
}

// S4 의미 확인(F6-11·F6-11m). 고르면 같은 질문을 그 후보로 다시 보낸다(reply.clarify_option_id). 입력 칸의 글은 직접 보충이다.
// 서버 후보는 이름(label)만 있어 보드의 후보 설명 줄은 그리지 않는다.
function ClarifyView({ turn, result, latest, locked, onAsk }: EntryProps & { turn: AgentTurn; result: ClarifyResult }) {
  const badgeId = useId()
  const promptId = useId()
  const question = askOf(turn.question)
  const active = latest && question !== null
  return <>
    <Question question={turn.question} />
    <span id={badgeId}><AiBadge>{M.aiBadge}</AiBadge></span>
    <div role="group" aria-labelledby={badgeId} aria-live="polite" className={styles.aiBox}>
      <p id={promptId} className={styles.clarifyPrompt}>{result.clarify.prompt}</p>
      <div role="group" aria-labelledby={promptId} className={styles.options}>
        {result.clarify.options.map((option) => <button key={option.option_id} type="button" className={styles.option}
          aria-disabled={!active || locked ? true : undefined}
          onClick={() => { if (active && !locked && question) onAsk(question, { reply: { turn_id: turn.turn_id, clarify_option_id: option.option_id } }) }}>
          {option.label}
        </button>)}
      </div>
      {active ? <p className={styles.partText}>{M.clarifyHelp}</p> : null}
    </div>
  </>
}

// S5 근거 없음·무관(F6-12b). AI가 답변을 만들지 않은 서버 고정 안내라 AI 생성 표시와 인용이 없다(결정 4·16).
function NoEvidenceView({ turn, latest, onClose }: EntryProps & { turn: AgentTurn }) {
  return <>
    <Question question={turn.question} />
    <div role="status" className={styles.statusBox}>
      <p className={styles.noticeTitleSmall}>{M.noEvidenceTitle('note')}</p>
      <p className={styles.noticeText}>{M.noEvidenceHelp}</p>
    </div>
    {latest ? <button type="button" className={styles.linkButton} onClick={onClose}>{M.backToNote}</button> : null}
  </>
}

// 주제 전환 확인(F6-20, 결정 38·40). 고르기 전에는 답변을 만들지 않고 보내기를 잠근다(AC-3). 카드가 뜨면 포커스를 카드 제목으로 옮긴다.
function TopicCheckView({ turn, latest, state, onAsk, onNewConversationAsk, onClose }: EntryProps & { turn: AgentTurn }) {
  const titleRef = useRef<HTMLParagraphElement>(null)
  const titleId = useId()
  const result = turn.result?.state === 'topic_check' ? turn.result : null
  const question = turn.question.text ? turn.question.text : null
  const active = latest && question !== null
  const pending = state.pending !== null
  useEffect(() => {
    if (active) titleRef.current?.focus({ preventScroll: true })
  }, [active])
  return <>
    <Question question={turn.question} />
    <div role="group" aria-labelledby={titleId} className={styles.statusBox}>
      <p id={titleId} ref={titleRef} tabIndex={-1} className={styles.noticeTitleSmall}>{M.topicTitle(result?.topic_check.current_topic ?? '')}</p>
      {active
        ? <>
            <p className={styles.noticeText}>{M.topicHelp}</p>
            <div className={styles.actions}>
              <Button variant="primary" aria-disabled={pending ? true : undefined}
                onClick={() => { if (!pending && question) onNewConversationAsk({ kind: 'free', text: question }) }}>{M.topicNew}</Button>
              <Button aria-disabled={pending ? true : undefined}
                onClick={() => { if (!pending && question) onAsk({ kind: 'free', text: question }, { reply: { turn_id: turn.turn_id, topic_choice: 'continue' } }, true) }}>{M.topicContinue}</Button>
            </div>
          </>
        : null}
    </div>
    {active ? <button type="button" className={styles.linkButton} onClick={onClose}>{M.backToNote}</button> : null}
  </>
}

// S9 변형: 출처만 권한 회수(F6-15b, 결정 7·11·15·17). 답변·출처·추천 질문은 그리지 않고 질문만 남긴다.
// 처음 영향받은 턴에 가림 안내와 '같은 질문 다시 하기'를 두고, 뒤쪽 턴은 함께 가렸다는 안내만 둔다. 뒤쪽 질문은 자동으로 다시 보내지 않는다.
function HiddenView({ turn, wide, locked, firstHidden, onAskAgain }: EntryProps & { turn: AgentTurn }) {
  const textless = questionText(turn.question) === ''
  const question = textless
    ? <>
        <div className={styles.caption}>{M.question}</div>
        <p className={styles.hiddenText}>{M.hiddenSuggested}</p>
      </>
    : <Question question={turn.question} />
  if (!wide) return question
  const canAskAgain = turn.hidden?.retry_allowed === true
  return <>
    {question}
    {firstHidden
      ? <div role="status" className={styles.statusBox}>
          <p className={styles.noticeTitleSmall}>{M.hiddenTitle}</p>
          <p className={styles.noticeText}>{M.hiddenHelp}</p>
          <p className={styles.noticeText}>{M.hiddenKept(canAskAgain)}</p>
          {canAskAgain
            ? <div className={styles.actions}>
                <Button variant="primary" aria-disabled={locked ? true : undefined} onClick={() => onAskAgain(turn)}>{M.askAgain}</Button>
              </div>
            : null}
        </div>
      : <div className={styles.hiddenBox}><p className={styles.hiddenText}>{M.hiddenFollowing}</p></div>}
  </>
}

// W5 다른 영역 선택(F6-8·F6-8m, 결정 20). 고르기 전까지 다음 질문의 문맥은 바뀌지 않고 보내기를 잠근다(AC-3).
function CandidateCard({ candidate, newLocked, onAdd, onNew, wide }: { candidate: AgentContextSelection; newLocked: boolean; onAdd: () => void; onNew: () => void; wide: boolean }) {
  const titleRef = useRef<HTMLHeadingElement>(null)
  const titleId = useId()
  const Heading = wide ? 'h3' : 'h2'
  useEffect(() => {
    titleRef.current?.focus({ preventScroll: true })
  }, [candidate])
  return <div role="group" aria-labelledby={titleId} className={wide ? styles.choiceBox : `${styles.choiceBox} ${styles.choiceBoxMobile}`}>
    <Heading id={titleId} ref={titleRef} tabIndex={-1} className={styles.choiceTitle}>{M.addTitle}</Heading>
    <p className={styles.choiceQuote}>{M.addQuote(candidate.text)}</p>
    <div className={styles.choiceActions}>
      <Button variant="primary" onClick={onAdd}>{M.addToConversation}</Button>
      <Button aria-disabled={newLocked ? true : undefined} onClick={onNew}>{M.addNewConversation}</Button>
    </div>
    <p className={styles.hintSmall}>{M.addHint}</p>
  </div>
}

// S7 중단(F6-14·F6-14b·F6-14m). 받다 만 답변은 숨기고, '중단한 질문 다시 넣기'로 질문을 입력 칸에 되돌린다(결정 1·5·12·13).
function StoppedView({ turn, latest, wide, state, draft, onDraft, onClose, onFocusInput }: EntryProps & { turn: AgentTurn }) {
  const [confirm, setConfirm] = useState(false)
  const confirmTitle = useRef<HTMLParagraphElement>(null)
  const confirmId = useId()
  const canReinsert = latest && state.cancelled?.turnId === turn.turn_id
  const question = questionText(state.cancelled?.question ?? turn.question)
  const hasDraft = draft.trim() !== ''
  useEffect(() => {
    if (confirm) confirmTitle.current?.focus({ preventScroll: true })
  }, [confirm])
  const reinsert = () => {
    if (!hasDraft) return onDraft(question)
    // 쓰던 초안이 있으면 바꾸기 전에 묻는다(F6-14b). 모바일 확인 보드는 아직 없어(결정 8) 모바일에서는 버튼을 잠근다.
    if (wide) setConfirm(true)
  }
  return <>
    <Question question={turn.question} />
    <div role="status" className={styles.statusBox}>
      <p className={styles.noticeTitleSmall}>{M.stopped}</p>
      {canReinsert && !confirm
        ? <>
            <p className={styles.noticeText}>{M.stoppedHidden}</p>
            <div className={styles.actions}>
              <Button aria-disabled={hasDraft && !wide ? true : undefined} onClick={reinsert}>{M.reinsert}</Button>
            </div>
            <p className={styles.hintSmall}>{M.reinsertHint}</p>
          </>
        : null}
    </div>
    {canReinsert && confirm
      ? <div role="group" aria-labelledby={confirmId} className={styles.confirmBox}
          onKeyDown={(event) => {
            // Esc는 패널이 아니라 확인 카드만 닫는다(취소와 같다). 문서의 Esc 처리는 defaultPrevented를 보고 건너뛴다.
            if (event.key !== 'Escape' || event.nativeEvent.isComposing) return
            event.preventDefault()
            setConfirm(false)
            onFocusInput()
          }}>
          <p id={confirmId} ref={confirmTitle} tabIndex={-1} className={styles.noticeTitleSmall}>{M.replaceTitle}</p>
          <div className={styles.caption}>{M.replaceCurrent}</div>
          <p className={styles.confirmText}>‘{draft}’</p>
          <div className={styles.caption}>{M.replaceNext}</div>
          <p className={styles.confirmText}>‘{question}’</p>
          <div className={styles.actions}>
            <Button variant="primary" onClick={() => { setConfirm(false); onDraft(question) }}>{M.replace}</Button>
            <Button onClick={() => { setConfirm(false); onFocusInput() }}>{M.cancel}</Button>
          </div>
          <p className={styles.hintSmall}>{M.replaceHint}</p>
        </div>
      : null}
    {wide && latest ? <button type="button" className={styles.linkButton} onClick={onClose}>{M.backToNote}</button> : null}
  </>
}

// PC 출처 보기의 패널 쪽(F6-4): 출처 카드, 노트 근거 안내, 대화가 남아 있다는 안내.
function SourcePanelInfo({ state, quote, question }: { state: SourceState | null; quote: string; question: string }) {
  if (!state || state.status === 'loading' || state.status === 'gone') return <p role="status" className={styles.noticeText}>{M.sourceLoading}</p>
  if (state.status === 'failed') return <p role="alert" className={styles.noticeTitleSmall}>{M.sourceFailed}</p>
  const { data } = state
  return <>
    <div className={styles.caption}>{M.sourceCard(data.source_kind, data.title, data.section ?? undefined)}</div>
    <p className={styles.intro}>{M.sourceGuide(data.source_kind)}</p>
    <div className={styles.kept}>
      <div className={styles.caption}>{M.conversationKept}</div>
      {question ? <p className={styles.keptText}>{M.sourceQuestion(question)}</p> : null}
      {quote ? <p className={styles.keptText}>{M.sourceQuote(quote)}</p> : null}
    </div>
  </>
}

// 모바일 출처 보기(F6-9). 대화 화면 대신 인용 문단을 보여 주고, 돌아가면 대화 스크롤과 초안이 그대로다.
function SourceMobile({ state, source }: { state: SourceState | null; source: OpenSource }) {
  if (!state || state.status === 'loading' || state.status === 'gone') return <p role="status" className={styles.noticeText}>{M.sourceLoading}</p>
  if (state.status === 'failed') return <p role="alert" className={styles.noticeTitleSmall}>{M.sourceFailed}</p>
  const { data } = state
  return <>
    <h2 className={styles.sourceHeading}>{data.title}</h2>
    <div className={styles.caption}>{M.sourceCard(data.source_kind, data.title, data.section ?? undefined)}</div>
    {data.changed_since_cited ? <p className={styles.noticeText}>{M.sourceChanged}</p> : null}
    <SourceParagraph ref_={source.ref} text={data.paragraph_text} section={data.section} />
    <p className={styles.hintSmall}>{M.sourceReturnHint}</p>
  </>
}

// 인용 문단. 노트 렌더러의 AI 모드로 그려 링크·이미지·HTML을 실행하지 않는다.
export function SourceParagraph({ ref_, text, section }: { ref_: number; text: string; section: string | null }): ReactNode {
  return <div className={styles.cited}>
    {section ? <h3 className={styles.citedSection}>{section}</h3> : null}
    <div className={styles.citedPill}>{M.sourceTitle(ref_)}</div>
    <div className={styles.citedText}><NoteBody mode="ai" body={text} citation={() => null} /></div>
  </div>
}

function SendIcon() {
  return <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 19V5M5 12l7-7 7 7" /></svg>
}

function StopIcon() {
  return <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="2" strokeLinejoin="round"><rect x="6" y="6" width="12" height="12" rx="1.5" /></svg>
}

function BackIcon() {
  return <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M19 12H5M12 19l-7-7 7-7" /></svg>
}

function DoneIcon() {
  return <svg aria-hidden="true" className={styles.stepIcon} width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="M8 12l3 3 5-6" /></svg>
}

function CurrentIcon() {
  return <svg aria-hidden="true" className={styles.stepIcon} width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="3" fill="currentColor" /></svg>
}
