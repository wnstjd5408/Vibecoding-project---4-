import { useEffect, useId, useRef } from 'react'
import type { ReactNode } from 'react'
import styles from './BottomSheet.module.css'
import { Scrim } from './Scrim.tsx'

type BottomSheetProps = {
  open: boolean
  // 닫기 버튼·막 누르기·Esc에서 불린다. 열림 여부(open)는 부모가 정한다.
  onClose: () => void
  // 시트 제목(예: 용어 이름). 스크린 리더가 시트의 이름으로 읽는다.
  title: ReactNode
  // 제목 위에 놓는 표시(예: Badge "사전", "AI 생성")
  badge?: ReactNode
  closeLabel?: string
  children: ReactNode
}

// 아래에서 올라오는 모달 시트. 브라우저 기본 모달(dialog)을 써서 아래를 브라우저가 처리한다.
//  - 열 때 첫 조작(닫기 버튼)에 포커스가 가고, 포커스는 시트 안에 갇힌다
//  - 배경은 조작할 수 없고, Esc로 닫힌다
//  - 닫으면 시트를 연 버튼으로 포커스가 돌아간다
export function BottomSheet({ open, onClose, title, badge, closeLabel = '닫기', children }: BottomSheetProps) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const titleId = useId()

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  // 시트가 열려 있는 동안 뒤 화면이 스크롤되지 않게 한다.
  useEffect(() => {
    if (!open) return
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previous
    }
  }, [open])

  return (
    <dialog
      ref={dialogRef}
      className={styles.dialog}
      aria-labelledby={titleId}
      onCancel={(event) => {
        // Esc는 브라우저가 바로 닫지 않게 막고, 부모가 open을 바꾸게 한다.
        event.preventDefault()
        onClose()
      }}
    >
      <Scrim onClick={onClose} />
      <div className={styles.sheet}>
        <div className={styles.grabRow}>
          <span aria-hidden="true" className={styles.handle} />
          <button type="button" className={styles.close} onClick={onClose}>
            {closeLabel}
          </button>
        </div>
        {badge ? <div className={styles.badge}>{badge}</div> : null}
        <h2 id={titleId} className={styles.title}>
          {title}
        </h2>
        {children}
      </div>
    </dialog>
  )
}
