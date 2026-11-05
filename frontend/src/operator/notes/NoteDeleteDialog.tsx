// F5-1f 노트 삭제 확인 창. 목업이 "문구 미정"으로 표시한 창이라 문구는 목업의 임시 문구를 그대로 쓴다(확정되면 이 한 곳만 고친다).
import { useEffect, useId, useRef } from 'react'
import { Button } from '../../components/index.ts'
import { Badge } from '../../components/Badge.tsx'
import styles from './Notes.module.css'

type NoteDeleteDialogProps = {
  title: string
  busy: boolean
  // 삭제에 실패했을 때 창 안에 보이는 안내
  error: string
  onConfirm: () => void
  onClose: () => void
}

export function NoteDeleteDialog({ title, busy, error, onConfirm, onClose }: NoteDeleteDialogProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()

  // 브라우저 기본 모달(dialog)을 써서 배경 조작을 막고 Esc로 닫는다.
  useEffect(() => {
    const dialog = ref.current
    if (dialog && !dialog.open) dialog.showModal()
    return () => {
      if (dialog?.open) dialog.close()
    }
  }, [])

  return (
    <dialog
      ref={ref}
      className={styles.dialog}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault()
        if (!busy) onClose()
      }}
    >
      <Badge>문구 미정</Badge>
      <h2 id={titleId} className={styles.dialogTitle}>
        노트를 삭제할까요?
      </h2>
      <p className={styles.dialogNote}>{title}</p>
      <p className={styles.dialogBody}>삭제하면 이 노트로 만든 AI 설명이 무효가 되고, 노트의 이미지 파일도 삭제 대상이 돼요.</p>
      {error ? (
        <p role="alert" className={styles.error}>
          오류: {error}
        </p>
      ) : null}
      <div className={styles.row}>
        <Button onClick={onConfirm} aria-disabled={busy ? 'true' : undefined}>
          삭제하기
        </Button>
        <Button variant="primary" onClick={onClose} aria-disabled={busy ? 'true' : undefined}>
          취소
        </Button>
      </div>
    </dialog>
  )
}
