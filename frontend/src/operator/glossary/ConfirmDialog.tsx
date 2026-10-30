import { useEffect, useId, useRef } from 'react'
import type { ReactNode } from 'react'
import styles from './Glossary.module.css'

type ConfirmDialogProps = { title: string; onClose: () => void; children: ReactNode }

// 화면 가운데 뜨는 확인 창(PC). 브라우저 기본 모달(dialog)을 써서 배경 조작을 막고 Esc로 닫는다.
// 디자인 시스템에 PC용 확인 창이 아직 없어 이 화면 안에 둔다.
export function ConfirmDialog({ title, onClose, children }: ConfirmDialogProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()

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
        onClose()
      }}
    >
      <h2 id={titleId} className={styles.dialogTitle}>
        {title}
      </h2>
      {children}
    </dialog>
  )
}
