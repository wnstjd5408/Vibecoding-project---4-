// F5-1b 노트 수정 / F5-1d 새 노트(MEG-80). 제목·학습일·본문을 쓰고 저장하거나 삭제한다.
// 과목·상위 노트·출처 링크는 확정 대기라 넣지 않는다. 이미지는 이 화면에서 올리지 않는다.
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { isApiError } from '../../api/client.ts'
import { Button, StateMessage, TextField } from '../../components/index.ts'
import { operatorPaths } from '../../routes/paths.ts'
import { useOperatorGuard } from '../useOperatorGuard.ts'
import { NoteDeleteDialog } from './NoteDeleteDialog.tsx'
import { deleteNote, getNote, saveNote } from './notesApi.ts'
import type { OperatorNote } from './notesApi.ts'
import styles from './Notes.module.css'

// 화면 문구. 실패·충돌 안내는 목업에 화면이 없어 임시 문구다(문구 미정, 확정되면 이 한 곳만 고친다).
const MESSAGES = {
  required: '제목, 학습일, 본문을 입력해 주세요.',
  saveFailed: '저장하지 못했어요. 잠시 뒤에 다시 시도해 주세요.',
  deleteFailed: '노트를 삭제하지 못했어요. 잠시 뒤에 다시 시도해 주세요.',
  // 저장하려는 사이 다른 곳에서 노트가 바뀌었다(409 stale_revision). 입력은 그대로 남아 있다.
  conflict: '이 노트가 다른 곳에서 바뀌었어요. 입력한 내용은 그대로 남아 있어요. 다시 불러오면 최신 내용으로 바뀌고 지금 입력한 내용은 사라져요.',
  reload: '다시 불러오기',
  noticeEdit: '안내: 제목이나 본문을 저장하면 이 노트로 만든 AI 설명이 무효가 돼요.',
  imageHint: '이미지는 이 화면에서 올리지 않아요. 가져오기로만 들어와요.',
  saved: '노트를 저장했어요.',
  deleted: '노트를 삭제했어요.',
} as const

type Load = { key: string; note: OperatorNote | null } | { key: string; state: 'notFound' | 'failed' }

export default function NoteEditPage() {
  const { noteId } = useParams()
  const creating = noteId === undefined
  const { onApiError } = useOperatorGuard()
  const [attempt, setAttempt] = useState(0)
  const [load, setLoad] = useState<Load | null>(null)

  const key = `${noteId ?? 'new'}:${attempt}`
  const current = creating ? { key, note: null } : load?.key === key ? load : null

  useEffect(() => {
    if (noteId === undefined) return
    let live = true
    getNote(Number(noteId)).then(
      (note) => live && setLoad({ key: `${noteId}:${attempt}`, note }),
      (failure) => {
        if (!live || onApiError(failure)) return
        setLoad({ key: `${noteId}:${attempt}`, state: isApiError(failure, 'not_found') ? 'notFound' : 'failed' })
      },
    )
    return () => {
      live = false
    }
  }, [noteId, attempt, onApiError])

  const heading = creating ? '새 노트' : '노트 수정'
  return (
    <main>
      <Link to={operatorPaths.home} className={styles.link}>
        노트 목록으로
      </Link>
      <h1 className={styles.title}>{heading}</h1>
      {!current ? (
        <StateMessage kind="loading" title="노트를 불러오는 중이에요" />
      ) : 'state' in current ? (
        current.state === 'notFound' ? (
          <StateMessage kind="empty" title="찾을 수 없는 노트예요" description="이미 삭제됐을 수 있어요. 목록에서 다시 골라 주세요." />
        ) : (
          <StateMessage
            kind="error"
            title="노트를 불러오지 못했어요"
            description="잠시 뒤에 다시 시도해 주세요."
            action={<Button onClick={() => setAttempt((count) => count + 1)}>다시 시도</Button>}
          />
        )
      ) : (
        // 다시 불러오면 서버의 최신 노트로 폼을 새로 그린다(입력이 사라진다).
        <NoteForm key={`${current.note?.id ?? 'new'}:${current.note?.revision ?? 0}`} note={current.note} onReload={() => setAttempt((count) => count + 1)} />
      )}
    </main>
  )
}

type NoteFormProps = { note: OperatorNote | null; onReload: () => void }

function NoteForm({ note, onReload }: NoteFormProps) {
  const navigate = useNavigate()
  const { onApiError } = useOperatorGuard()
  const creating = note === null
  const [title, setTitle] = useState(note?.title ?? '')
  const [studiedOn, setStudiedOn] = useState(note?.studiedOn ?? '')
  const [body, setBody] = useState(note?.body ?? '')
  const [error, setError] = useState('')
  const [conflict, setConflict] = useState(false)
  const [busy, setBusy] = useState(false)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [deleteError, setDeleteError] = useState('')

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    if (!title.trim() || !studiedOn || !body.trim()) {
      setError(MESSAGES.required)
      return
    }
    setBusy(true)
    setError('')
    setConflict(false)
    try {
      await saveNote(note?.id ?? null, { title: title.trim(), studiedOn, body }, note?.revision ?? null)
      navigate(operatorPaths.home, { state: { notice: MESSAGES.saved } })
    } catch (failure) {
      if (isApiError(failure, 'conflict', 'stale_revision')) {
        // 다른 곳에서 바뀌었다. 입력은 지우지 않고 안내만 한다.
        setConflict(true)
      } else if (!onApiError(failure)) {
        setError(MESSAGES.saveFailed)
      }
      setBusy(false)
    }
  }

  async function handleDelete() {
    if (!note || busy) return
    setBusy(true)
    setDeleteError('')
    try {
      await deleteNote(note.id)
      navigate(operatorPaths.home, { state: { notice: MESSAGES.deleted } })
    } catch (failure) {
      if (!onApiError(failure)) setDeleteError(MESSAGES.deleteFailed)
      setBusy(false)
    }
  }

  return (
    <form className={styles.formCard} onSubmit={handleSubmit}>
      <TextField label="제목" required maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)} />
      <TextField label="학습일" type="date" required value={studiedOn} onChange={(event) => setStudiedOn(event.target.value)} />
      <TextField
        label="본문"
        multiline
        required
        className={styles.body}
        hint={MESSAGES.imageHint}
        value={body}
        onChange={(event) => setBody(event.target.value)}
      />
      {!creating ? <p className={styles.notice}>{MESSAGES.noticeEdit}</p> : null}
      {conflict ? (
        <div role="alert" className={styles.conflict}>
          <p>{MESSAGES.conflict}</p>
          <Button onClick={onReload}>{MESSAGES.reload}</Button>
        </div>
      ) : null}
      {error ? (
        <p role="alert" className={styles.error}>
          오류: {error}
        </p>
      ) : null}
      <div className={styles.row}>
        <Button type="submit" variant="primary" aria-disabled={busy ? 'true' : undefined}>
          저장
        </Button>
        <Link to={operatorPaths.home} className={styles.cancel}>
          취소
        </Link>
      </div>
      {!creating ? (
        <div className={styles.divider}>
          <Button onClick={() => setConfirmingDelete(true)}>노트 삭제</Button>
        </div>
      ) : null}
      {confirmingDelete && note ? (
        <NoteDeleteDialog
          title={note.title}
          busy={busy}
          error={deleteError}
          onConfirm={() => void handleDelete()}
          onClose={() => {
            setConfirmingDelete(false)
            setDeleteError('')
          }}
        />
      ) : null}
    </form>
  )
}
