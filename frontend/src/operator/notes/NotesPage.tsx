// F5-1a 운영자 노트 목록 + F5-1f 삭제 확인(MEG-80). 과목으로 걸러 보고, 수정·삭제·공개 전환으로 이어진다.
import { useEffect, useState } from 'react'
import type { ChangeEvent } from 'react'
import { Link, useLocation } from 'react-router'
import { Button, StateMessage } from '../../components/index.ts'
import { Badge } from '../../components/Badge.tsx'
import { IconLinkButton } from '../../components/IconButton.tsx'
import { operatorPaths } from '../../routes/paths.ts'
import { useOperatorGuard } from '../useOperatorGuard.ts'
import { NoteDeleteDialog } from './NoteDeleteDialog.tsx'
import { noteEditPath } from './noteEditPath.ts'
import { deleteNote, listNotes, setPublished } from './notesApi.ts'
import type { NoteList, NoteListItem, NoteSubject } from './notesApi.ts'
import styles from './Notes.module.css'

// 화면 문구. 실패 안내는 목업에 화면이 없어 임시 문구다(문구 미정, 확정되면 이 한 곳만 고친다).
const MESSAGES = {
  deleteFailed: '노트를 삭제하지 못했어요. 잠시 뒤에 다시 시도해 주세요.',
  publishFailed: '공개 여부를 바꾸지 못했어요. 잠시 뒤에 다시 시도해 주세요.',
  deleted: '노트를 삭제했어요.',
} as const

type Result = { query: string; data: NoteList } | { query: string; failed: true }

// 저장·삭제 뒤 이 화면으로 올 때 넘겨 준 안내
function readNotice(state: unknown): string {
  const value = (state as { notice?: unknown } | null)?.notice
  return typeof value === 'string' ? value : ''
}

export default function NotesPage() {
  const location = useLocation()
  const { onApiError } = useOperatorGuard()
  const [subjectId, setSubjectId] = useState<number | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<Result | null>(null)
  // 걸러도 과목 목록은 그대로라서 마지막으로 받은 것을 둔다(다시 불러오는 동안 선택 칸이 비지 않게).
  const [subjects, setSubjects] = useState<NoteSubject[]>([])
  const [notice, setNotice] = useState(() => readNotice(location.state))
  const [actionError, setActionError] = useState('')
  const [target, setTarget] = useState<NoteListItem | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [dialogError, setDialogError] = useState('')
  const [publishingId, setPublishingId] = useState<number | null>(null)

  const query = `${subjectId}:${attempt}`
  const current = result?.query === query ? result : null

  useEffect(() => {
    let live = true
    const key = `${subjectId}:${attempt}`
    listNotes(subjectId).then(
      (data) => {
        if (!live) return
        setSubjects(data.subjects)
        setResult({ query: key, data })
      },
      (failure) => {
        if (!live || onApiError(failure)) return
        setResult({ query: key, failed: true })
      },
    )
    return () => {
      live = false
    }
  }, [subjectId, attempt, onApiError])

  function updateNotes(change: (notes: NoteListItem[]) => NoteListItem[]) {
    setResult((old) => (old && 'data' in old ? { ...old, data: { ...old.data, notes: change(old.data.notes) } } : old))
  }

  async function handleDelete() {
    if (!target || deleting) return
    setDeleting(true)
    setDialogError('')
    try {
      await deleteNote(target.id)
      updateNotes((notes) => notes.filter((note) => note.id !== target.id))
      setNotice(MESSAGES.deleted)
      setTarget(null)
    } catch (failure) {
      // 권한 오류면 로그인 상태를 다시 읽어 경로 보호가 화면을 내보낸다. 그 밖에는 창 안에서 알린다.
      if (!onApiError(failure)) setDialogError(MESSAGES.deleteFailed)
    }
    setDeleting(false)
  }

  async function handlePublish(note: NoteListItem) {
    if (publishingId !== null) return
    setPublishingId(note.id)
    setActionError('')
    setNotice('')
    try {
      const updated = await setPublished(note.id, !note.isPublished)
      updateNotes((notes) => notes.map((item) => (item.id === updated.id ? updated : item)))
    } catch (failure) {
      if (!onApiError(failure)) setActionError(MESSAGES.publishFailed)
    }
    setPublishingId(null)
  }

  return (
    <main>
      <div className={styles.head}>
        <h1 className={styles.title}>노트</h1>
        <div className={styles.row}>
          <label className={styles.filterLabel} htmlFor="note-filter">
            과목
          </label>
          <select
            id="note-filter"
            className={styles.filterSelect}
            value={subjectId === null ? '' : String(subjectId)}
            onChange={(event: ChangeEvent<HTMLSelectElement>) => {
              setNotice('')
              setSubjectId(event.target.value === '' ? null : Number(event.target.value))
            }}
          >
            <option value="">전체</option>
            {subjects.map((subject) => (
              <option key={subject.id} value={subject.id}>
                {subject.name}
              </option>
            ))}
          </select>
          <IconLinkButton label="새 노트" to={operatorPaths.noteNew} className={styles.newNote}>
            <PlusIcon />
          </IconLinkButton>
        </div>
      </div>

      {notice ? (
        <p role="status" className={styles.status}>
          {notice}
        </p>
      ) : null}
      {actionError ? (
        <p role="alert" className={styles.error}>
          오류: {actionError}
        </p>
      ) : null}

      {!current ? (
        <StateMessage kind="loading" title="노트를 불러오는 중이에요" />
      ) : 'failed' in current ? (
        <StateMessage
          kind="error"
          title="노트를 불러오지 못했어요"
          description="잠시 뒤에 다시 시도해 주세요."
          action={<Button onClick={() => setAttempt((count) => count + 1)}>다시 시도</Button>}
        />
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <caption>노트 {current.data.notes.length}개</caption>
            <thead>
              <tr>
                <th scope="col">제목</th>
                <th scope="col">과목</th>
                <th scope="col">학습일</th>
                <th scope="col">공개</th>
                <th scope="col">동작</th>
              </tr>
            </thead>
            <tbody>
              {current.data.notes.map((note) => (
                <tr key={note.id}>
                  <td>
                    <strong>{note.title}</strong>
                  </td>
                  <td>{note.subjects.length > 0 ? note.subjects.map((subject) => subject.name).join(' · ') : '-'}</td>
                  <td>{note.studiedOn}</td>
                  <td>
                    <Badge tone={note.isPublished ? 'ai' : 'dictionary'}>{note.isPublished ? '공개' : '비공개'}</Badge>
                  </td>
                  <td>
                    <div className={styles.row}>
                      <Link to={noteEditPath(note.id)} className={styles.link}>
                        수정
                      </Link>
                      <button type="button" className={styles.link} onClick={() => setTarget(note)}>
                        삭제
                      </button>
                      <button
                        type="button"
                        className={styles.link}
                        aria-disabled={publishingId !== null ? 'true' : undefined}
                        onClick={() => void handlePublish(note)}
                      >
                        {note.isPublished ? '비공개로 바꾸기' : '공개로 바꾸기'}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {current.data.notes.length === 0 ? <p className={styles.empty}>등록된 노트가 없어요.</p> : null}
        </div>
      )}

      {target ? (
        <NoteDeleteDialog
          title={target.title}
          busy={deleting}
          error={dialogError}
          onConfirm={() => void handleDelete()}
          onClose={() => {
            setTarget(null)
            setDialogError('')
          }}
        />
      ) : null}
    </main>
  )
}

function PlusIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <path d="M12 5v14M5 12h14" />
    </svg>
  )
}
