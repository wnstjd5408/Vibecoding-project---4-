import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router'
import { apiFetch, isApiError } from '../api/client.ts'
import type { NoteReadResponse } from '../api/types.ts'
import { AccountMenu } from '../account/AccountMenu.tsx'
import { useAuth } from '../auth/useAuth.ts'
import { AppHeader, BottomSheet, Button, LinkButton, StateMessage } from '../components/index.ts'
import { NoteBody } from '../notes/NoteBody.tsx'
import { userPaths } from '../routes/paths.ts'
import styles from './NoteReadPage.module.css'

// 화면 문구. 임시이며 확정되면 이 한 곳만 고친다(PR에 기록).
const MESSAGES = {
  loading: '노트를 불러오는 중이에요',
  notFound: '찾을 수 없는 노트예요',
  notFoundAction: '노트 목록으로',
  failed: '노트를 불러오지 못했어요',
  rateLimited: '요청이 많아요. 잠시 뒤에 다시 시도해 주세요.',
  retry: '다시 시도',
  termPending: '용어 설명은 아직 준비 중이에요.',
}

type Result = { key: string; data: NoteReadResponse } | { key: string; error: 'not_found' | 'failed' | 'rate_limited' }

export default function NoteReadPage() {
  const { noteId = '' } = useParams()
  // 노트가 바뀌면 이전 노트의 상태(펼친 시트·이미지 실패)를 버린다.
  return <NoteRead key={noteId} noteId={noteId} />
}

function NoteRead({ noteId }: { noteId: string }) {
  const auth = useAuth()
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<Result | null>(null)
  const [termId, setTermId] = useState<number | null>(null)
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
  const term = note?.glossary_terms.find((item) => item.term_id === termId)

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
        : <article>
            <h1 className={styles.title}>{current.data.title}</h1>
            <p className={styles.meta}>{[...current.data.subjects.map((item) => item.name), ...(current.data.studied_on ? [current.data.studied_on] : [])].join(' · ')}</p>
            <NoteBody body={current.data.body_markdown} spans={current.data.glossary_spans} images={current.data.images}
              brokenImages={brokenImages} onTerm={setTermId} onImageError={onImageError} />
          </article>}
    </main>
    {/* 용어를 누르면 열리는 시트. MEG-74는 용어 이름만 보이고, 설명·이미지·즐겨찾기는 MEG-76이 이 안을 채운다. */}
    <BottomSheet open={term !== undefined} onClose={() => setTermId(null)} title={term?.label ?? ''}>
      <p className={styles.pending}>{MESSAGES.termPending}</p>
    </BottomSheet>
  </div>
}
