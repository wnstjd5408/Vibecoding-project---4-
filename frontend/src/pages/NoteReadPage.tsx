import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { apiFetch, isApiError } from '../api/client.ts'
import type { NoteReadResponse } from '../api/types.ts'
import { AccountMenu } from '../account/AccountMenu.tsx'
import { useAuth } from '../auth/useAuth.ts'
import { AiExplainSheet } from '../ai/AiExplainSheet.tsx'
import { useWideLayout } from '../components/useWideLayout.ts'
import { toCodePointRange } from '../ai/explain.ts'
import { AppHeader, Button, LinkButton, SelectionAction, StateMessage } from '../components/index.ts'
import { cx } from '../components/cx.ts'
import { TermSheet } from '../glossary/TermSheet.tsx'
import { isLoginRequired } from '../loginPrompt/isLoginRequired.ts'
import { useLoginPrompt } from '../loginPrompt/useLoginPrompt.ts'
import { NoteBody } from '../notes/NoteBody.tsx'
import { sourceRangeOfSelection } from '../notes/selection.ts'
import { userPaths } from '../routes/paths.ts'
import type { ExplainTarget } from '../ai/explain.ts'
import { AgentPanel } from '../agent/AgentPanel.tsx'
import { INITIAL_AGENT_UI } from '../agent/agentUi.ts'
import type { AgentUi } from '../agent/agentUi.ts'
import { AgentSourceDocument } from '../agent/AgentSourceDocument.tsx'
import { shownAgentView, useAgentView } from '../agent/agentView.ts'
import { AGENT_MESSAGES } from '../agent/messages.ts'
import { agentPreviewEnabled } from '../agent/preview.ts'
import { useAgentConversation } from '../agent/useAgentConversation.ts'
import { useAgentSource } from '../agent/useAgentSource.ts'
import type { OpenSource } from '../agent/useAgentSource.ts'
import styles from './NoteReadPage.module.css'

// AI 설명 버튼 크기·간격(px). 선택 영역의 손잡이와 겹치지 않도록 선택 끝에서 조금 띄운다.
const BUTTON_GAP = 24
const BUTTON_WIDTH = 100

type PickedText = { start: number; end: number; top: number; left: number }

// 화면 문구. 임시이며 확정되면 이 한 곳만 고친다(PR에 기록).
const MESSAGES = {
  loading: '노트를 불러오는 중이에요',
  notFound: '찾을 수 없는 노트예요',
  notFoundAction: '노트 목록으로',
  failed: '노트를 불러오지 못했어요',
  rateLimited: '요청이 많아요. 잠시 뒤에 다시 시도해 주세요.',
  retry: '다시 시도',
}

type Result = { key: string; data: NoteReadResponse } | { key: string; error: 'not_found' | 'failed' | 'rate_limited' }

export default function NoteReadPage() {
  const { noteId = '' } = useParams()
  // 노트가 바뀌면 이전 노트의 상태(펼친 시트·이미지 실패)를 버린다.
  return <NoteRead key={noteId} noteId={noteId} />
}

function NoteRead({ noteId }: { noteId: string }) {
  const auth = useAuth()
  const { handleLoginRequired, openLoginPrompt, closeLoginPrompt, panelOpen: loginPanelOpen } = useLoginPrompt()
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<Result | null>(null)
  // 열린 용어 시트. openId는 열 때마다 올라가 같은 용어를 다시 열어도 새로 불러온다.
  const [openTerm, setOpenTerm] = useState<{ termId: number; openId: number } | null>(null)
  const openCount = useRef(0)
  // 본문에서 고른 글(원문 위치와 버튼 위치). 위치를 계산하지 못하는 선택이면 null이라 AI 설명 버튼이 보이지 않는다.
  const [pick, setPick] = useState<PickedText | null>(null)
  // 열린 AI 설명 시트. 요청 위치·개정은 버튼을 누른 때의 값이고 시트가 열려 있는 동안 바뀌지 않는다.
  const [openAi, setOpenAi] = useState<{ target: ExplainTarget; text: string; openId: number } | null>(null)
  const articleRef = useRef<HTMLElement>(null)
  // PC 폭(1024px 이상)이면 용어·AI 설명을 오른쪽 사이드 패널로 보인다. 용어 링크는 패널과 aria-expanded·aria-controls로 잇는다.
  const wide = useWideLayout()
  const panelId = useId()
  // 마지막으로 누른 용어 링크. 패널을 닫으면 포커스가 여기로 돌아간다.
  const lastTermLink = useRef<HTMLElement | null>(null)
  // 버튼을 누르는 동안 브라우저가 선택을 풀어도(터치) 버튼이 사라지지 않게 한다.
  const pressing = useRef(false)
  const [brokenImages, setBrokenImages] = useState<ReadonlySet<string>>(new Set())
  const key = `${noteId}:${attempt}`
  const valid = /^\d+$/.test(noteId)
  // CS Agent 'AI에게 질문'(MEG-258). 대화 상태는 이 노트 화면에 두어 패널을 닫았다 열어도 대화와 초안이 남는다(MEG-255 메모).
  // 진입점은 T6e(MEG-259) 전까지 개발 서버의 ?cs-agent=1에서만 열린다(agent/preview.ts). 기본은 지금처럼 'AI 설명'이다.
  const [searchParams] = useSearchParams()
  const agentPreview = agentPreviewEnabled(searchParams)
  const { state: agentState, controller: agent } = useAgentConversation(valid ? Number(noteId) : 0)
  const [agentOpen, setAgentOpen] = useState(false)
  const [agentUi, setAgentUi] = useState<AgentUi>(INITIAL_AGENT_UI)
  const onAgentUi = useCallback((patch: Partial<AgentUi> | ((ui: AgentUi) => Partial<AgentUi>)) => setAgentUi((previous) => ({ ...previous, ...(typeof patch === 'function' ? patch(previous) : patch) })), [])
  const [agentSource, setAgentSource] = useState<OpenSource | null>(null)
  const agentSourceState = useAgentSource(agentSource)
  // PC 보기 방식(패널·떠 있는 창·전체 화면, MEG-261). 마지막 보기 방식으로 다시 연다.
  const [agentView, setAgentView] = useAgentView()
  const agentShown = wide && agentOpen ? shownAgentView(agentView, wide, agentSource !== null) : null
  // PC 출처 보기에서 노트 자리에 출처를 보여 주는 동안 노트를 읽던 위치. 돌아오면 되살린다.
  const noteScroll = useRef(0)
  const current = valid && result?.key === key ? result : null
  // 이미지 토큰마다 E05를 다시 부르는 것은 한 번뿐이다. 새 URL도 실패하면 대체 글로 둔다(Q-N11).
  const refreshedTokens = useRef(new Set<string>())
  const refreshing = useRef<Promise<NoteReadResponse> | null>(null)

  useEffect(() => {
    if (!valid) return
    const controller = new AbortController()
    apiFetch<NoteReadResponse>(`/api/notes/${noteId}`, { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) setResult({ key, data })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        const reason = isApiError(error, 'not_found') ? 'not_found' : isApiError(error, 'rate_limited') ? 'rate_limited' : 'failed'
        setResult({ key, error: reason })
      })
    return () => controller.abort()
  }, [noteId, key, valid])

  // 이미지가 안 열리면(서명 URL 만료 등) E05를 다시 불러 새 URL을 받는다. 동시에 여러 이미지가 실패해도 부르는 것은 한 번이다.
  const onImageError = useCallback((token: string, failedUrl: string) => {
    const fail = () => setBrokenImages((previous) => new Set(previous).add(token))
    if (refreshedTokens.current.has(token)) return fail()
    refreshedTokens.current.add(token)
    refreshing.current ??= apiFetch<NoteReadResponse>(`/api/notes/${noteId}`)
      .then((data) => {
        setResult({ key, data })
        return data
      })
      .finally(() => { refreshing.current = null })
    // 다시 받은 URL이 방금 실패한 URL과 같으면 img의 src가 그대로라 다시 불러오지 않는다. 새 URL이 없는 경우와 함께 실패로 닫는다.
    refreshing.current.then((data) => {
      if (data.images[token]?.url === failedUrl || !data.images[token]) fail()
    }, fail)
  }, [noteId, key])

  const note = current && 'data' in current ? current.data : null
  const noteRevision = note?.revision
  const noteBody = note?.body_markdown
  const loginStatus = auth.status

  // 본문에서 글을 고르면 원문 위치를 계산해 AI 설명 버튼을 띄운다. 비었거나 위치를 모르면 버튼을 숨긴다.
  useEffect(() => {
    if (noteRevision === undefined || noteBody === undefined || loginStatus === 'loading') return
    const update = () => {
      if (pressing.current) return
      const article = articleRef.current
      const root = article?.querySelector('[data-note-body]')
      const selection = document.getSelection()
      if (!article || !root || !selection || selection.rangeCount === 0 || selection.isCollapsed) return setPick(null)
      const range = selection.getRangeAt(0)
      const source = sourceRangeOfSelection(root, range)
      if (!source || noteBody.slice(source.start, source.end).trim() === '') return setPick(null)
      const rect = range.getBoundingClientRect()
      const box = article.getBoundingClientRect()
      setPick({
        ...source,
        top: rect.bottom - box.top + BUTTON_GAP,
        left: Math.max(0, Math.min(rect.left - box.left, box.width - BUTTON_WIDTH)),
      })
    }
    document.addEventListener('selectionchange', update)
    return () => document.removeEventListener('selectionchange', update)
  }, [noteRevision, noteBody, loginStatus])
  const term = note?.glossary_terms.find((item) => item.term_id === openTerm?.termId)
  // 시트 안 즐겨찾기가 401 login_required를 받으면 용어 시트를 먼저 닫고 로그인 안내를 연다. 안내를 닫으면 누른 용어 링크로 포커스가 돌아간다.
  const onFavoriteLoginRequired = (error: unknown) => {
    if (!isLoginRequired(error)) return false
    setOpenTerm(null)
    // PC 폭에서는 용어 패널을 닫고 같은 자리에 로그인 안내 패널을 연다. 닫으면 마지막으로 누른 용어 링크로 포커스가 돌아간다.
    return handleLoginRequired(error, { panel: true, returnFocus: () => lastTermLink.current })
  }
  // AI 설명 버튼: 방문자는 요청 없이 로그인 안내를 열고, 로그인한 사용자는 E09 요청을 보내는 시트를 연다.
  const askAi = () => {
    pressing.current = false
    if (!note || !pick) return
    if (agentPreview) return openAgent()
    const text = note.body_markdown.slice(pick.start, pick.end)
    // 버튼은 누르면 사라지므로, 시트·안내를 닫았을 때 포커스가 돌아갈 곳으로 본문을 먼저 잡아 둔다.
    articleRef.current?.focus({ preventScroll: true })
    document.getSelection()?.removeAllRanges()
    setPick(null)
    // 패널은 한 번에 하나만 연다(PC 폭에서는 모달이 아니라 용어 패널이 열린 채 AI 설명을 누를 수 있다).
    setOpenTerm(null)
    if (auth.role === 'visitor') return openLoginPrompt()
    if (loginPanelOpen) closeLoginPrompt()
    openCount.current += 1
    setOpenAi({ target: { noteId: note.id, revision: note.revision, ...toCodePointRange(note.body_markdown, pick.start, pick.end) }, text, openId: openCount.current })
  }
  // 시트 안 E09가 401 login_required를 받으면(세션 만료) AI 설명 시트를 먼저 닫고 로그인 안내를 연다.
  const onAiLoginRequired = useCallback((error: unknown) => {
    if (!isLoginRequired(error)) return false
    setOpenAi(null)
    return handleLoginRequired(error)
  }, [handleLoginRequired])
  // 노트가 바뀌었다는 안내(409 stale_revision)에서 시트를 닫고 노트를 다시 불러온다. 사용자는 단어를 다시 고른다.
  const onReloadNote = useCallback(() => {
    setOpenAi(null)
    setPick(null)
    setAttempt((value) => value + 1)
  }, [])
  // 'AI에게 질문'(임시 연결): 선택만으로는 아무 요청도 보내지 않고 질문 준비 화면(F6-1)을 연다.
  // 대화가 이미 있으면 그 대화를 그대로 보여 준다. 다른 영역을 고른 뒤의 '현재 대화에 추가'·'새 대화' 선택(F6-8)은 T6d 범위다.
  const openAgent = () => {
    if (!note || !pick) return
    const text = note.body_markdown.slice(pick.start, pick.end)
    articleRef.current?.focus({ preventScroll: true })
    document.getSelection()?.removeAllRanges()
    setPick(null)
    setOpenTerm(null)
    setOpenAi(null)
    if (auth.role === 'visitor') return openLoginPrompt()
    if (loginPanelOpen) closeLoginPrompt()
    const started = agentState.conversation !== null || agentState.pending !== null || agentState.turns.length > 0
    if (!started) {
      const range = toCodePointRange(note.body_markdown, pick.start, pick.end)
      setAgentUi((previous) => ({ ...previous, selection: { noteId: note.id, revision: note.revision, ...range, text }, excluded: false, expanded: false }))
    }
    setAgentOpen(true)
  }
  const closeAgentSource = useCallback(() => {
    setAgentSource((current) => {
      if (current) {
        // 대화로 돌아오면 출처를 연 버튼으로 포커스를 돌린다.
        const opener = current.opener
        requestAnimationFrame(() => { if (opener?.isConnected) opener.focus({ preventScroll: true }) })
      }
      return null
    })
  }, [])
  const closeAgent = useCallback(() => {
    setAgentSource(null)
    setAgentOpen(false)
  }, [])
  const openAgentSource = (turnId: string, ref: number, opener: HTMLElement) => {
    if (agentSource === null) noteScroll.current = window.scrollY
    openCount.current += 1
    setAgentSource({ turnId, ref, opener, openId: openCount.current })
  }
  // PC 출처 보기를 닫으면 노트를 읽던 위치로 돌아간다(9절).
  const showingSource = wide && agentOpen && agentSource !== null
  useEffect(() => {
    if (!showingSource) window.scrollTo({ top: noteScroll.current })
  }, [showingSource])
  // 세션이 끝나 질문이 401 login_required를 받으면 패널을 닫고 로그인 안내를 연다.
  const onAgentLoginRequired = useCallback(() => {
    closeAgent()
    openLoginPrompt()
  }, [closeAgent, openLoginPrompt])
  const showTerm = (termId: number, link: HTMLElement) => {
    lastTermLink.current = link
    setOpenAi(null)
    closeAgent()
    if (loginPanelOpen) closeLoginPrompt() // 로그인 안내 패널이 열려 있으면 닫는다(같은 자리의 용어 패널이 뒤에 가려지지 않게)
    openCount.current += 1
    setOpenTerm({ termId, openId: openCount.current })
  }
  // 패널이 열려 있으면 본문 오른쪽 480px를 비워 패널이 본문을 가리지 않게 한다(PC 폭에서만).
  // 떠 있는 창이면 창 폭만큼 비운다(F6-3f). 전체 화면은 패널과 같은 배치를 둔 채 노트를 가려서, 패널로 돌아오면 읽던 위치가 그대로다(결정 43).
  const panelReserved = wide && (term !== undefined || openAi !== null || loginPanelOpen || (agentOpen && agentShown !== 'floating'))
  // 전체 화면 동안에는 가린 노트가 굴러가지 않게 문서 스크롤을 잠근다. 잠근 동안 위치는 그대로라 패널로 돌아오면 읽던 위치다(결정 43).
  // inert는 포커스와 보조기기만 막고 휠·키보드 스크롤은 막지 않는다. 스크롤 막대가 있던 화면은 막대 자리를 남겨 머리가 옆으로 밀리지 않게 한다.
  // 위치를 따로 되돌리지 않는다. 출처 보기를 닫을 때 noteScroll로 옮기는 스크롤(아래 효과)을 덮어쓰지 않기 위해서다.
  const agentFullscreen = agentShown === 'fullscreen'
  useLayoutEffect(() => {
    if (!agentFullscreen) return
    const root = document.documentElement
    const previous = { overflow: root.style.overflow, gutter: root.style.scrollbarGutter }
    const hadScrollbar = window.innerWidth > root.clientWidth
    root.style.overflow = 'hidden'
    if (hadScrollbar) root.style.scrollbarGutter = 'stable'
    return () => {
      root.style.overflow = previous.overflow
      root.style.scrollbarGutter = previous.gutter
    }
  }, [agentFullscreen])
  const pageClass = cx(styles.page, panelReserved && styles.panelOpen, agentShown === 'floating' && styles.floatingOpen)

  return <div className={pageClass}>
    <AppHeader title="CS 학습 노트" backTo={userPaths.noteList} backLabel="목록" wide stickyOnWide actions={
      auth.status === 'loading' ? null
        : auth.role === 'visitor' ? <LinkButton to={userPaths.login}>로그인</LinkButton> : <AccountMenu />
    } />
    <main className={styles.main} aria-busy={valid && !current} inert={agentShown === 'fullscreen'}>
      {!valid || (current && 'error' in current && current.error === 'not_found')
        ? <StateMessage kind="empty" title={MESSAGES.notFound} headingLevel={2}
            action={<Link className={styles.link} to={userPaths.noteList}>{MESSAGES.notFoundAction}</Link>} />
        : !current ? <StateMessage kind="loading" title={MESSAGES.loading} headingLevel={2} />
        : 'error' in current ? <StateMessage kind="error" headingLevel={2}
            title={current.error === 'rate_limited' ? MESSAGES.rateLimited : MESSAGES.failed}
            action={<Button onClick={() => setAttempt((value) => value + 1)}>{MESSAGES.retry}</Button>} />
        : <>
          {showingSource && agentSourceState ? <AgentSourceDocument state={agentSourceState} ref_={agentSource.ref} /> : null}
          <article ref={articleRef} className={styles.article} tabIndex={-1} hidden={showingSource}>
            <h1 className={styles.title}>{current.data.title}</h1>
            <p className={styles.meta}>{[...current.data.subjects.map((item) => item.name), ...(current.data.studied_on ? [current.data.studied_on] : [])].join(' · ')}</p>
            <NoteBody body={current.data.body_markdown} spans={current.data.glossary_spans} images={current.data.images}
              brokenImages={brokenImages} onTerm={showTerm} onImageError={onImageError}
              panelId={wide ? panelId : undefined} expandedTermId={wide ? (term ? openTerm?.termId ?? null : null) : undefined} />
            {pick
              ? <SelectionAction top={pick.top} left={pick.left}
                  onPointerDown={(event) => { pressing.current = true; event.preventDefault() }}
                  onPointerCancel={() => { pressing.current = false }}
                  onPointerLeave={() => { pressing.current = false }}
                  onClick={askAi}>{agentPreview ? AGENT_MESSAGES.title : 'AI 설명'}</SelectionAction>
              : null}
          </article>
        </>}
    </main>
    <AgentPanel open={agentOpen} wide={wide} view={agentView} onView={setAgentView} state={agentState} controller={agent} ui={agentUi} onUi={onAgentUi}
      source={agentSource} sourceState={agentSourceState} onOpenSource={openAgentSource} onCloseSource={closeAgentSource}
      onClose={closeAgent} onLoginRequired={onAgentLoginRequired} returnFocus={() => articleRef.current} />
    <AiExplainSheet open={openAi !== null} onClose={() => setOpenAi(null)} openId={openAi?.openId ?? 0} target={openAi?.target ?? null} text={openAi?.text ?? ''} onLoginRequired={onAiLoginRequired} onReloadNote={onReloadNote} returnFocus={() => articleRef.current} />
    {/* 용어를 누르면 열리는 시트(F1-3). 시트 안 즐겨찾기 버튼(MEG-90)과 로그인 안내 연결(MEG-77)이 이 안에 있다. */}
    <TermSheet open={term !== undefined} onClose={() => setOpenTerm(null)} openId={openTerm?.openId ?? 0} termId={openTerm?.termId ?? null} label={term?.label ?? ''} onLoginRequired={onFavoriteLoginRequired}
      panelId={panelId} returnFocus={() => lastTermLink.current} />
  </div>
}
