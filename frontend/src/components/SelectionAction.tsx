import type { ButtonHTMLAttributes } from 'react'
import styles from './SelectionAction.module.css'
import { Button } from './Button.tsx'
import { cx } from './cx.ts'

type SelectionActionProps = { children?: string } & Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'>

// 노트 본문에서 글자를 고르면 선택 영역 바로 아래에 뜨는 "AI 설명" 버튼.
// 선택된 글자를 감싸는 position: relative 요소 안에 놓는다. 선택 위치를 계산하는 일은 하지 않는다(화면 티켓 범위).
export function SelectionAction({ className, children = 'AI 설명', ...rest }: SelectionActionProps) {
  return (
    <Button variant="primary" className={cx(styles.action, className)} {...rest}>
      {children}
    </Button>
  )
}
