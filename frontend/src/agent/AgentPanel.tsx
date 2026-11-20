// CS Agent 'AI에게 질문' 패널(MEG-258, T6c). 화면 목록 2~12번(MEG-239 1단계 결과)의 PC 패널과 모바일 전체 높이 화면이다.
//  - PC(1024px 이상): 오른쪽 480px 패널. 모달이 아니라서 노트를 계속 읽고 고를 수 있다(F6-1~F6-19).
//  - 모바일: 전체 높이 대화 화면(모달). 노트 화면은 뒤에 그대로 있어 닫으면 읽던 위치로 돌아간다(F6-1m~F6-18m).
//  - 대화 상태는 노트 화면(NoteReadPage)이 useAgentConversation으로 가진다. 이 패널은 상태를 그리기만 하고, 닫아도 대화와 초안은 남는다.
//  - 모바일 보드가 없는 상태(지연 안내, 단계 없는 준비 중, 긴 답변의 '새 답변 보기', 다시 넣기 확인, 사용 제한)는 모바일에서 그리지 않는다
//    (2026-11-20 결정 8, MEG-262 디자인 → MEG-263에서 반영).
//  - 예외 상태(의미 확인·근거 일부·근거 없음·교정·주제 전환·다른 영역 선택·접근 변경)는 T6d(MEG-260), 떠 있는 창·전체 화면은 T6f(MEG-261)다.
//  - 다시 답하기 화면과 버튼은 만들지 않는다(MEG-228, spec 부록 A).
//  - 새 질문 입구가 닫히면(closed: 노출 중단 플래그·503, MEG-259) 입력 칸·빠른 질문·추천 질문·'새 대화'·'중단한 질문 다시 넣기'를 숨긴다.
//    지금 대화, 이전 대화 보기, 출처 보기, 진행 중인 답변의 중단은 그대로 둔다(E28·E30·E31·E32는 플래그와 무관하다).
import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent, ReactNode } from 'react'
import { AiBadge, Button } from '../components/index.ts'
import { AiAnswer } from '../notes/AiAnswer.tsx'
import type { AiAnswerFigure } from '../notes/AiAnswer.tsx'
import { NoteBody } from '../notes/NoteBody.tsx'
import { canRetry } from './conversation.ts'
import type { AgentConversationController, AgentFailure, AgentState, PendingTurn, StepView } from './conversation.ts'
import { AGENT_MESSAGES as M, PRESETS, questionLabel, questionText, topicLabelOf } from './messages.ts'
import { MAX_QUESTION, quoteOf, sectionsOf } from './agentUi.ts'
import type { AgentUi } from './agentUi.ts'
import type { AgentFigure, AgentQuestion, AgentSource, AgentTurn, AskQuestion, CreateConversationRequest } from './types.ts'
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
  // 새 질문 입구가 닫혔다(노출 중단 플래그 또는 E27·E29의 503, agent/availability.ts)
  closed?: boolean
}

type Entry =
  | { kind: 'turn'; key: string; turn: AgentTurn }
  | { kind: 'pending'; key: string; pending: PendingTurn }
  | { kind: 'failure'; key: string; failure: AgentFailure }

const isLimitLike = (failure: AgentFailure | null) => failure !== null && failure.kind === 'limit_reached'
// 503(노출 중단). 다시 확인해도 열리지 않으므로 사용 제한 카드와 따로 그린다(MEG-259).
const isUnavailable = (failure: AgentFailure | null) => failure !== null && failure.kind === 'service_unavailable'
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

export function AgentPanel(props: AgentPanelProps) {
  const { open, wide, state, controller, ui, onUi, source, onClose, onCloseSource, returnFocus, closed = false } = props
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
  const contextSelection = conversation ? (conversation.context_selections[0] ?? null) : null
  const selectionText = conversation ? (contextSelection?.text_preview ?? null) : (ui.selection?.text ?? null)
  const hasSelection = selectionText !== null && !ui.excluded
  const topic = conversation?.topic_label || (ui.selection && !ui.excluded ? topicLabelOf(ui.selection.text) : '')
  // 보내기 잠금: 생성 중, 다시 시도 전의 요청 실패(F6-6p), 다시 확인 전의 사용 제한(F6-17, 모바일 보드 없음)
  const failureLock = failure !== null && (limitLike ? wide : isRetryable(failure))
  const locked = pending !== null || failureLock || closed
  // 입구가 닫혀도 진행 중인 답변은 끝까지 받고 중단할 수 있어야 하므로 그동안은 입력 칸(중단 버튼)을 남긴다.
  const composerHidden = closed && pending === null
  const fresh = state.turns.length === 0 && pending === null && failure === null

  const entries: Entry[] = state.turns.map((turn) => ({ kind: 'turn', key: turn.turn_id, turn }))
  if (pending) entries.push({ kind: 'pending', key: 'pending', pending })
  // 모바일 사용 제한 보드가 없어(결정 8) 모바일에서는 사용 제한을 대화 항목으로 넣지 않는다. 넣으면 빈 항목이 앞 답변을 가린다.
  else if (failure?.question && !(limitLike && !wide)) entries.push({ kind: 'failure', key: 'failure', failure })
  const collapsed = !ui.expanded && entries.length > 1
  const shown = collapsed ? entries.slice(-1) : entries
  const lastKey = entries.at(-1)?.key ?? null

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
  // 누른 버튼(빠른 질문, 추천 질문, 다시 시도, 중단)은 누른 뒤 사라지므로 포커스를 입력 칸으로 옮긴다.
  const ask = (question: AskQuestion) => {
    if (locked) return
    if (source) onCloseSource()
    const excludes = conversation && ui.excluded ? conversation.context_selections.map((item) => item.selection_id) : []
    controller.ask(question, { context: contextFor(), ...(excludes.length > 0 ? { exclude_selection_ids: excludes } : {}) }).then(afterRun, () => {})
    focusInput()
  }
  const retry = () => {
    void controller.retry().then(afterRun)
    focusInput()
  }
  const text = ui.draft.trim()
  const canSend = !locked && text !== '' && [...text].length <= MAX_QUESTION
  const send = () => {
    if (!canSend) return
    ask({ kind: 'free', text })
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
    onUi({ excluded: false, expanded: false })
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
    : fresh ? M.labelFirst : M.labelNext

  const header = wide
    ? <div className={styles.head}>
        <h2 id={titleId} ref={titleRef} tabIndex={-1} className={styles.title}>{source ? M.sourceTitle(source.ref) : M.title}</h2>
        <div className={styles.headActions}>
          {source
            ? <button type="button" className={styles.iconButton} aria-label={M.backToConversation} onClick={onCloseSource}><BackIcon /></button>
            : <>
                {closed ? null : <button type="button" className={styles.headButton} aria-disabled={pending ? true : undefined} onClick={newConversation}>{M.newConversation}</button>}
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
          ? (closed ? null : <AskIntro disabled={!hasSelection} onPreset={(preset) => ask({ kind: 'preset', preset })} />)
          : <>
              {collapsed
                ? <button type="button" className={styles.previous} onClick={expand}>{M.previous(conversation?.topic_label ?? topic, questionLabel(entryQuestion(entries[0])))}</button>
                : null}
              {state.loadFailure && !collapsed ? <p role="alert" className={styles.smallError}>{M.previousFailed}</p> : null}
              {shown.map((entry) => <div key={entry.key} data-entry="" className={styles.entry}>
                <EntryView entry={entry} latest={entry.key === lastKey} wide={wide} state={state} controller={controller}
                  hasSelection={hasSelection} locked={locked} closed={closed} draft={ui.draft} onRetry={retry}
                  onDraft={(draft) => { onUi({ draft }); focusInput() }} onAsk={ask} onSource={openSource} onClose={onClose} onFocusInput={focusInput} />
              </div>)}
            </>}
      </div>
      {showNewAnswer
        ? <div className={styles.newAnswerBar}>
            <button type="button" className={styles.newAnswer} onClick={() => { scrollToLatest(); setUnseen(false) }}>{M.newAnswer}</button>
          </div>
        : null}
      {composerHidden
        ? <div className={wide ? styles.composerArea : styles.mobileComposerArea}>
            <p className={styles.noticeText}>{M.closedNotice}</p>
          </div>
        : <div className={wide ? styles.composerArea : styles.mobileComposerArea}>
        {hasSelection && !(source && !wide)
          ? <div className={styles.chip}>
              <span className={styles.chipText}>{M.selectionChip(selectionText ?? '')}</span>
              <div className={styles.chipActions}>
                {wide ? <button type="button" className={styles.chipButton} aria-expanded={showSelection} aria-controls={selectionId} onClick={() => setShowSelection((value) => !value)}>{M.selectionFull}</button> : null}
                <button type="button" className={styles.chipButton} onClick={() => { onUi({ excluded: true }); setShowSelection(false) }}>{M.exclude}</button>
              </div>
            </div>
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
      </div>}
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
  // 새 질문 입구가 닫혔다. 새 질문을 보내는 버튼(추천 질문, 다시 넣기)을 그리지 않는다.
  closed: boolean
  draft: string
  onRetry: () => void
  onDraft: (draft: string) => void
  onAsk: (question: AskQuestion) => void
  onSource: (turnId: string, ref: number, opener: HTMLElement) => void
  onClose: () => void
  onFocusInput: () => void
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
  // 503(노출 중단, MEG-259): 질문은 남기고, 새 질문을 받을 수 없다고 알린다. 지금 대화는 계속 읽을 수 있다. 보드가 없어 PC·모바일이 같다.
  if (isUnavailable(failure)) {
    return <>
      <Question question={failure.question ?? { kind: 'free' }} />
      <div role="alert" className={styles.alertBox}>
        <p className={styles.noticeTitle}>{M.unavailable}</p>
        <p className={styles.noticeText}>{M.unavailableHelp}</p>
        <div className={styles.actions}>
          <Button onClick={onClose}>{M.keepReading}</Button>
        </div>
      </div>
    </>
  }
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
  const { turn, latest, locked, closed, onAsk, onSource } = props
  const badgeId = useId()
  if (turn.status === 'cancelled') return <StoppedView {...props} />
  const result = sectionsOf(turn.result)
  const sources: AgentSource[] = result?.sources ?? []
  const suggestions = latest && result && !closed ? (result.suggestions ?? []).slice(0, 3) : []
  return <>
    <Question question={turn.question} />
    {result
      ? <>
          <span id={badgeId}><AiBadge>{M.aiBadge}</AiBadge></span>
          <div role="group" aria-labelledby={badgeId} className={styles.aiBox}>
            <AiAnswer sections={result.sections} figures={figuresOf(result.figures)} sources={sources}
              onSource={(ref, button) => onSource(turn.turn_id, ref, button)} />
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
        </>
      : null}
    {/* 의미 확인·근거 없음·주제 전환 결과와 가린 턴은 T6d(MEG-260)에서 그린다. */}
  </>
}

// S7 중단(F6-14·F6-14b·F6-14m). 받다 만 답변은 숨기고, '중단한 질문 다시 넣기'로 질문을 입력 칸에 되돌린다(결정 1·5·12·13).
function StoppedView({ turn, latest, wide, state, closed, draft, onDraft, onClose, onFocusInput }: EntryProps & { turn: AgentTurn }) {
  const [confirm, setConfirm] = useState(false)
  const confirmTitle = useRef<HTMLParagraphElement>(null)
  const confirmId = useId()
  const canReinsert = latest && !closed && state.cancelled?.turnId === turn.turn_id
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
  if (!state || state.status === 'loading') return <p role="status" className={styles.noticeText}>{M.sourceLoading}</p>
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
  if (!state || state.status === 'loading') return <p role="status" className={styles.noticeText}>{M.sourceLoading}</p>
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
