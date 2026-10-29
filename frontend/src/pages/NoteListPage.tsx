import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { apiFetch, isApiError } from '../api/client.ts'
import type { NoteListResponse } from '../api/types.ts'
import { useAuth } from '../auth/useAuth.ts'
import { AppHeader, Button, LinkButton, NoteListItem, StateMessage } from '../components/index.ts'
import { Chip } from '../components/Chip.tsx'
import { AccountMenu } from '../account/AccountMenu.tsx'
import { noteReadPath, operatorPaths, userPaths } from '../routes/paths.ts'
import styles from './NoteListPage.module.css'

type Result = { query: string; data: NoteListResponse } | { query: string; error: string }

// 역할이 바뀌면 이전 역할의 목록을 버린다. 운영자 응답이 방문자 화면에 남지 않게 한다.
export default function NoteListPage() {
  const auth = useAuth()
  return <NoteList key={auth.role} />
}

function NoteList() {
  const auth = useAuth()
  const [params, setParams] = useSearchParams()
  const subject = params.get('subject_id') ?? ''
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<Result | null>(null)
  const [subjects, setSubjects] = useState<NoteListResponse['subjects']>([])
  const query = `${subject}:${attempt}:${auth.status}`
  const current = result?.query === query ? result : null

  useEffect(() => {
    if (auth.status === 'loading') return
    const controller = new AbortController()
    apiFetch<NoteListResponse>('/api/notes', {
      query: { subject_id: subject || undefined }, signal: controller.signal,
    }).then((data) => {
      if (controller.signal.aborted) return
      setSubjects(data.subjects)
      setResult({ query, data })
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return
      const message = isApiError(error, 'validation_failed')
        ? '과목을 확인할 수 없어요'
        : isApiError(error, 'rate_limited') ? '요청이 많아요. 잠시 뒤에 다시 시도해 주세요.' : '노트를 불러오지 못했어요'
      setResult({ query, error: message })
    })
    return () => controller.abort()
  }, [subject, query, auth.status])

  function selectSubject(id?: number) {
    setParams((previous) => {
      const next = new URLSearchParams(previous)
      if (id === undefined) next.delete('subject_id')
      else next.set('subject_id', String(id))
      return next
    })
  }

  return <div className={styles.page}>
    <AppHeader title="CS 학습 노트" actions={<>
      {auth.role === 'operator' && <Link className={styles.link} to={operatorPaths.home}>운영자 메뉴</Link>}
      {auth.role === 'visitor'
        ? <LinkButton to={userPaths.login}>로그인</LinkButton>
        : <AccountMenu />}
    </>} />
    <main>
      <h1 className={styles.heading}>과목</h1>
      <div className={styles.filters} role="group" aria-label="과목 선택">
        <Chip selected={!subject} onClick={() => selectSubject()}>전체</Chip>
        {subjects.map((item) => <Chip key={item.id} selected={subject === String(item.id)} onClick={() => selectSubject(item.id)}>{item.name}</Chip>)}
      </div>
      <div className={styles.quiz}><Link className={styles.link} to={auth.role === 'visitor' ? userPaths.login : userPaths.quiz}>오늘의 퀴즈</Link></div>
      <section className={styles.notes} aria-label="노트 목록" aria-busy={!current}>
        {!current ? <div className={styles.message}><StateMessage kind="loading" title="노트를 불러오는 중이에요" headingLevel={2} /></div>
          : 'error' in current ? <div className={styles.message}><StateMessage kind="error" title={current.error} headingLevel={2}
            action={<Button onClick={() => setAttempt((value) => value + 1)}>다시 시도</Button>} /></div>
          : current.data.notes.length === 0 ? <div className={styles.message}><StateMessage kind="empty" headingLevel={2}
            title={subject ? '이 과목에는 노트가 없어요.' : '아직 볼 수 있는 노트가 없어요.'} /></div>
          : current.data.notes.map((note) => <NoteListItem key={note.id} to={noteReadPath(note.id)} title={note.title}
            meta={[...note.subjects.map((item) => item.name), ...(note.studied_on ? [note.studied_on] : [])].join(' · ')} />)}
      </section>
    </main>
  </div>
}
