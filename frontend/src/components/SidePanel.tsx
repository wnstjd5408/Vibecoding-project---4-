import { useEffect, useId, useRef } from 'react'
import type { ReactNode } from 'react'
import styles from './SidePanel.module.css'

type SidePanelProps = {
  // 용어 링크가 aria-controls로 가리키는 패널 id
  id?: string
  open: boolean
  // 닫기 버튼·Esc에서 불린다. 열림 여부(open)는 부모가 정한다.
  onClose: () => void
  // 패널 제목(예: 용어 이름). 스크린 리더가 패널의 이름으로 읽는다.
  title: ReactNode
  // 제목 위 왼쪽에 놓는 표시(예: Badge "사전", "AI 생성")
  badge?: ReactNode
  closeLabel?: string
  // 제목 아래 간격(CSS 값). 비우면 8px이다. 목업은 AI 설명 패널만 12px이다.
  titleGap?: string
  // 닫을 때 포커스를 돌려줄 요소. 없으면 열 때 포커스가 있던 요소로 돌아간다(예: 마지막으로 누른 용어 링크).
  returnFocus?: () => HTMLElement | null
  children: ReactNode
}

// PC 폭(1024px 이상)의 오른쪽 사이드 패널. BottomSheet와 달리 모달이 아니다.
//  - 스크림이 없고 배경도 비활성이 아니라서, 본문을 계속 읽고 스크롤할 수 있다(스크롤 잠금 없음)
//  - 처음 열릴 때만 제목으로 포커스가 간다. 열린 채 내용이 바뀌어도(다른 용어) 포커스를 옮기지 않는다
//  - 닫기 버튼과 Esc로 닫는다. 닫으면 포커스가 돌아간다
// 브라우저 dialog를 show()로 열어 역할(dialog)과 이름 연결(aria-labelledby)을 그대로 쓴다.
export function SidePanel({ id, open, onClose, title, badge, closeLabel = '닫기', titleGap, returnFocus, children }: SidePanelProps) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const titleRef = useRef<HTMLHeadingElement>(null)
  const titleId = useId()
  const opener = useRef<HTMLElement | null>(null)
  // 최신 값을 이펙트에서 쓰되, 값이 바뀌어도 열고 닫는 동작을 다시 실행하지 않게 ref에 둔다.
  const latest = useRef({ returnFocus, onClose })
  useEffect(() => {
    latest.current = { returnFocus, onClose }
  })

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open && !dialog.open) {
      opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
      dialog.show()
      titleRef.current?.focus({ preventScroll: true })
    } else if (!open && dialog.open) {
      // 다른 패널이 막 열려 포커스를 가져갔다면(용어 패널이 닫히면서 AI 설명 패널이 열리는 경우) 그 포커스를 빼앗지 않는다.
      const active = document.activeElement
      const holder = active instanceof HTMLElement ? active.closest('dialog') : null
      dialog.close()
      if (holder !== null && holder !== dialog) return
      // 돌려줄 요소가 화면에서 사라졌으면(노트가 다시 그려진 경우) 열 때 포커스가 있던 요소를 쓴다.
      const preferred = latest.current.returnFocus?.()
      const target = preferred?.isConnected ? preferred : opener.current
      if (target?.isConnected) target.focus({ preventScroll: true })
    }
  }, [open])

  // Esc로 닫는다. 비모달 dialog는 Esc로 저절로 닫히지 않으므로 직접 듣는다.
  // 위에 모달(오류 신고 입력 시트·로그인 안내 시트)이 열려 있으면 그 시트가 Esc를 맡는다.
  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented || event.isComposing) return
      if (document.querySelector('dialog:modal')) return
      latest.current.onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open])

  return (
    <dialog ref={dialogRef} id={id} className={styles.panel} aria-labelledby={titleId}>
      <div className={styles.top}>
        <div className={styles.badge}>{badge}</div>
        <button type="button" className={styles.close} onClick={onClose}>
          {closeLabel}
        </button>
      </div>
      <h2 id={titleId} ref={titleRef} tabIndex={-1} className={styles.title} style={titleGap ? { marginBottom: titleGap } : undefined}>
        {title}
      </h2>
      {children}
    </dialog>
  )
}
