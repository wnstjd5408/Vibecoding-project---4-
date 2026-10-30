import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router'
import { apiFetch, isApiError } from '../api/client.ts'
import type { NoteReadResponse } from '../api/types.ts'
import { AccountMenu } from '../account/AccountMenu.tsx'
import { useAuth } from '../auth/useAuth.ts'
import { AiExplainSheet } from '../ai/AiExplainSheet.tsx'
import { toCodePointRange } from '../ai/explain.ts'
import { AppHeader, Button, LinkButton, SelectionAction, StateMessage } from '../components/index.ts'
import { TermSheet } from '../glossary/TermSheet.tsx'
import { isLoginRequired } from '../loginPrompt/isLoginRequired.ts'
import { useLoginPrompt } from '../loginPrompt/useLoginPrompt.ts'
import { NoteBody } from '../notes/NoteBody.tsx'
import { sourceRangeOfSelection } from '../notes/selection.ts'
import { userPaths } from '../routes/paths.ts'
import type { ExplainTarget } from '../ai/explain.ts'
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
  const { handleLoginRequired, openLoginPrompt } = useLoginPrompt()
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
  // 버튼을 누르는 동안 브라우저가 선택을 풀어도(터치) 버튼이 사라지지 않게 한다.
  const pressing = useRef(false)
  const [brokenImages, setBrokenImages] = useState<ReadonlySet<string>>(new Set())
  const key = `${noteId}:${attempt}`
  const valid = /^\d+$/.test(noteId)
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
    return handleLoginRequired(error)
  }
  // AI 설명 버튼: 방문자는 요청 없이 로그인 안내를 열고, 로그인한 사용자는 E09 요청을 보내는 시트를 연다.
  const askAi = () => {
    pressing.current = false
    if (!note || !pick) return
    const text = note.body_markdown.slice(pick.start, pick.end)
    // 버튼은 누르면 사라지므로, 시트·안내를 닫았을 때 포커스가 돌아갈 곳으로 본문을 먼저 잡아 둔다.
    articleRef.current?.focus({ preventScroll: true })
    document.getSelection()?.removeAllRanges()
    setPick(null)
    if (auth.role === 'visitor') return openLoginPrompt()
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
  const showTerm = (termId: number) => {
    openCount.current += 1
    setOpenTerm({ termId, openId: openCount.current })
  }

  return <div className={styles.page}>
    <AppHeader backTo={userPaths.noteList} backLabel="목록" actions={
      auth.status === 'loading' ? null
        : auth.role === 'visitor' ? <LinkButton to={userPaths.login}>로그인</LinkButton> : <AccountMenu />
    } />
    <main className={styles.main} aria-busy={valid && !current}>
      {!valid || (current && 'error' in current && current.error === 'not_found')
        ? <StateMessage kind="empty" title={MESSAGES.notFound} headingLevel={2}
            action={<Link className={styles.link} to={userPaths.noteList}>{MESSAGES.notFoundAction}</Link>} />
        : !current ? <StateMessage kind="loading" title={MESSAGES.loading} headingLevel={2} />
        : 'error' in current ? <StateMessage kind="error" headingLevel={2}
            title={current.error === 'rate_limited' ? MESSAGES.rateLimited : MESSAGES.failed}
            action={<Button onClick={() => setAttempt((value) => value + 1)}>{MESSAGES.retry}</Button>} />
        : <article ref={articleRef} className={styles.article} tabIndex={-1}>
            <h1 className={styles.title}>{current.data.title}</h1>
            <p className={styles.meta}>{[...current.data.subjects.map((item) => item.name), ...(current.data.studied_on ? [current.data.studied_on] : [])].join(' · ')}</p>
            <NoteBody body={current.data.body_markdown} spans={current.data.glossary_spans} images={current.data.images}
              brokenImages={brokenImages} onTerm={showTerm} onImageError={onImageError} />
            {pick
              ? <SelectionAction top={pick.top} left={pick.left}
                  onPointerDown={(event) => { pressing.current = true; event.preventDefault() }}
                  onPointerCancel={() => { pressing.current = false }}
                  onPointerLeave={() => { pressing.current = false }}
                  onClick={askAi}>AI 설명</SelectionAction>
              : null}
          </article>}
    </main>
    <AiExplainSheet open={openAi !== null} onClose={() => setOpenAi(null)} openId={openAi?.openId ?? 0} target={openAi?.target ?? null} text={openAi?.text ?? ''} onLoginRequired={onAiLoginRequired} onReloadNote={onReloadNote} />
    {/* 용어를 누르면 열리는 시트(F1-3). 시트 안 즐겨찾기 버튼(MEG-90)과 로그인 안내 연결(MEG-77)이 이 안에 있다. */}
    <TermSheet open={term !== undefined} onClose={() => setOpenTerm(null)} openId={openTerm?.openId ?? 0} termId={openTerm?.termId ?? null} label={term?.label ?? ''} onLoginRequired={onFavoriteLoginRequired} />
  </div>
}
