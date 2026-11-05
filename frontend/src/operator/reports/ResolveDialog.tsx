// 신고 처리 확인 창. 목업에 없는 창이라 모양은 노트 삭제 확인 창(F5-1f)을 따르고 문구는 모두 합성 예시다(문구 미정, 확정되면 이 한 곳만 고친다).
import { useEffect, useId, useRef, useState } from 'react'
import { Button } from '../../components/index.ts'
import { Badge } from '../../components/Badge.tsx'
import type { Report } from './reportsApi.ts'
import styles from './Reports.module.css'

const MESSAGES = {
  title: '신고를 처리할까요?',
  invalidate: 'AI 설명도 무효화',
  invalidateHint: '켜면 이 신고의 AI 설명이 더 이상 쓰이지 않아요.',
  confirm: '처리하기',
  cancel: '취소',
} as const

type ResolveDialogProps = {
  report: Report
  busy: boolean
  // 처리에 실패했을 때 창 안에 보이는 안내
  error: string
  onConfirm: (invalidateExplanation: boolean) => void
  onClose: () => void
}

export function ResolveDialog({ report, busy, error, onConfirm, onClose }: ResolveDialogProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  const hintId = useId()
  // 기본값은 끈다(Q-N7).
  const [invalidate, setInvalidate] = useState(false)
  // 무효화할 AI 설명이 있는 신고(용어 설명)에서만 고른다. E26은 문항 신고의 invalidate_explanation을 무시하므로 문항에서는 선택지를 보이지 않는다.
  const explainable = report.kind === '용어 설명'

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
        {MESSAGES.title}
      </h2>
      <p className={styles.dialogReport}>{report.title}</p>
      {explainable ? (
        <>
          <label className={styles.check}>
            <input type="checkbox" checked={invalidate} aria-describedby={hintId} onChange={(event) => setInvalidate(event.target.checked)} />
            {MESSAGES.invalidate}
          </label>
          <p id={hintId} className={styles.hint}>
            {MESSAGES.invalidateHint}
          </p>
        </>
      ) : null}
      {error ? (
        <p role="alert" className={styles.error}>
          오류: {error}
        </p>
      ) : null}
      <div className={styles.row}>
        <Button onClick={() => onConfirm(explainable && invalidate)} aria-disabled={busy ? 'true' : undefined}>
          {MESSAGES.confirm}
        </Button>
        <Button variant="primary" onClick={onClose} aria-disabled={busy ? 'true' : undefined}>
          {MESSAGES.cancel}
        </Button>
      </div>
    </dialog>
  )
}
