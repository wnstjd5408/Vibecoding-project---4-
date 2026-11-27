// /guides/:slug 가이드 화면 (MEG-288, PRD v0.5 AC-8~AC-11). 기능 플래그(VITE_GUIDES_ENABLED)가 켜진 빌드에만 경로가 있다.
// 화면 본문은 GuidePage(MEG-287)이고, 여기서는 목록 확인·불러오기·닫기를 맡는다.
// 이 화면은 서버에 기록을 남기지 않는다. 주소로 바로 들어와 닫을 때만 E05로 노트가 열리는지 확인한다(GET, 새 기록 없음).
import { useEffect, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router'
import { apiFetch, isApiError } from '../api/client.ts'
import { AppHeader, Button, LinkButton, StateMessage } from '../components/index.ts'
import { GuidePage } from '../guides/GuidePage.tsx'
import { findGuide, type GuideEntryState } from '../guides/catalog.ts'
import { loadGuide, peekGuide } from '../guides/loadGuide.ts'
import type { GuideFile, GuideIndexEntry } from '../guides/types.ts'
import { noteReadPath, userPaths } from '../routes/paths.ts'
import styles from '../guides/Guide.module.css'

// 화면 문구. 캔버스 G0-E1m(볼 수 없음)·G1-1m(닫기 막대)를 따른다.
const MESSAGES = {
  close: '닫기',
  barLabel: '단계별 가이드',
  loading: '가이드를 불러오는 중이에요',
  failed: '가이드를 불러오지 못했어요',
  retry: '다시 시도',
  unavailableTitle: '이 가이드는 지금 볼 수 없어요',
  unavailableBody: '공개가 멈췄거나 지워진 가이드예요. 노트 목록에서 다른 노트를 골라 주세요.',
  toList: '노트 목록으로',
}

export default function GuideReadPage() {
  const { slug = '' } = useParams()
  // 다른 가이드로 바뀌면 단계 위치와 불러오기 상태를 새로 시작한다.
  return <GuideRead key={slug} slug={slug} />
}

function GuideRead({ slug }: { slug: string }) {
  const entry = findGuide(slug)
  // 공개 목록에 없으면 제목과 내용을 드러내지 않는다(PRD AC-9). 가이드 파일도 불러오지 않는다.
  if (!entry) return <GuideUnavailable />
  return <GuideLoaded entry={entry} />
}

type Load = { state: 'loading' } | { state: 'ok'; guide: GuideFile } | { state: 'failed' }

function GuideLoaded({ entry }: { entry: GuideIndexEntry }) {
  const close = useCloseGuide(entry)
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<{ attempt: number; load: Load } | null>(null)
  const ready = peekGuide(entry.slug)
  const load: Load = ready ? { state: 'ok', guide: ready } : result?.attempt === attempt ? result.load : { state: 'loading' }

  useEffect(() => {
    if (peekGuide(entry.slug)) return
    let alive = true
    loadGuide(entry.slug).then(
      (guide) => {
        if (alive) setResult({ attempt, load: { state: 'ok', guide } })
      },
      () => {
        if (alive) setResult({ attempt, load: { state: 'failed' } })
      },
    )
    return () => {
      alive = false
    }
  }, [entry.slug, attempt])

  // 같은 탭에서 실패한 파일을 다시 받아도 또 실패할 수 있다(브라우저가 실패한 모듈을 기억하는 경우).
  // 노트 쪽 연결(GuideLink)과 같이, 처음 불러오기와 첫 다시 시도가 모두 실패한 뒤에는 다시 시도가 페이지를 새로 고친다(MEG-305, PRD AC-10).
  // 새로 고쳐도 기록(history state)이 남아 닫기는 전과 같이 동작한다.
  const retry = () => (attempt >= 1 ? window.location.reload() : setAttempt((n) => n + 1))

  const header = (
    <div className={styles.topBar}>
      <button type="button" className={styles.topClose} onClick={close.run} disabled={close.busy}>
        {MESSAGES.close}
      </button>
      <span className={styles.topLabel}>{MESSAGES.barLabel}</span>
    </div>
  )

  if (load.state === 'ok') return <GuidePage guide={load.guide} header={header} />
  return (
    <div className={styles.page}>
      {header}
      <main className={styles.wrap}>
        {load.state === 'loading' ? (
          <StateMessage kind="loading" title={MESSAGES.loading} headingLevel={2} />
        ) : (
          <StateMessage kind="error" title={MESSAGES.failed} headingLevel={2}
            action={<Button variant="primary" onClick={retry}>{MESSAGES.retry}</Button>} />
        )}
      </main>
    </div>
  )
}

// 닫기(PRD AC-8).
//  - 노트의 연결로 들어왔으면 브라우저 기록에서 한 칸 돌아간다. 뒤로 가기와 같은 길이라 노트가 읽던 위치를 되살린다.
//  - 주소로 바로 들어왔으면 E05로 연결된 노트를 확인한다. 열리면 노트 처음으로, 404면 노트 목록으로 간다.
//    그 밖의 실패(네트워크·요청 많음)는 노트로 보낸다. 노트 화면이 자기 오류 안내와 다시 시도를 보인다.
//  - 가이드 화면 기록을 남기지 않도록 기록을 바꿔 끼운다(replace). 닫은 뒤 뒤로 가기로 가이드가 다시 열리지 않는다.
function useCloseGuide(entry: GuideIndexEntry) {
  const navigate = useNavigate()
  const location = useLocation()
  const [busy, setBusy] = useState(false)
  const state = location.state as Partial<GuideEntryState> | null
  // 이 가이드의 노트에서 왔고, 그 앞 기록이 남아 있을 때만 한 칸 돌아간다. 복원된 기록처럼 앞 칸이 없으면 주소로 들어온 경우와 같이 처리한다.
  const historyIndex = (window.history.state as { idx?: number } | null)?.idx ?? 0
  const fromNote = state?.from === 'note' && state.noteId === entry.note_id && historyIndex > 0
  const run = () => {
    if (fromNote) return void navigate(-1)
    if (!/^[1-9][0-9]*$/.test(entry.note_id)) return void navigate(userPaths.noteList, { replace: true })
    setBusy(true)
    // 응답이 오래 걸려도 닫기가 막히지 않게 8초 뒤에는 노트로 보낸다. 노트 화면이 자기 상태를 보인다.
    const controller = new AbortController()
    const timer = window.setTimeout(() => controller.abort(), 8000)
    apiFetch(`/api/notes/${entry.note_id}`, { signal: controller.signal })
      .then(
        () => navigate(noteReadPath(entry.note_id), { replace: true }),
        (error: unknown) => navigate(isApiError(error, 'not_found') ? userPaths.noteList : noteReadPath(entry.note_id), { replace: true }),
      )
      .finally(() => window.clearTimeout(timer))
  }
  return { run, busy }
}

function GuideUnavailable() {
  return (
    <div className={styles.page}>
      <AppHeader backTo={userPaths.noteList} />
      <main className={styles.unavailable}>
        <h1 className={styles.unavailableTitle}>{MESSAGES.unavailableTitle}</h1>
        <p className={styles.unavailableBody}>{MESSAGES.unavailableBody}</p>
        <LinkButton variant="primary" to={userPaths.noteList} className={styles.unavailableAction}>{MESSAGES.toList}</LinkButton>
      </main>
    </div>
  )
}
