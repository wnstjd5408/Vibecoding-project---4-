import type { ComponentPropsWithRef } from 'react'
import styles from './SelectionAction.module.css'
import { Button } from './Button.tsx'
import { cx } from './cx.ts'

type SelectionActionProps = {
  children?: string
  // 가장 가까운 position이 있는 조상 기준 위치(px). 화면이 선택 영역(Selection)의 위치를 읽어 넘긴다.
  // 주지 않으면 조상의 왼쪽 아래에 뜬다.
  top?: number
  left?: number
} & Omit<ComponentPropsWithRef<'button'>, 'children'>

// 노트 본문에서 글자를 고르면 선택 영역 근처에 뜨는 "AI 설명" 버튼.
// 선택 영역의 위치를 읽는 일은 하지 않고, 본문 DOM을 감싸지도 않는다. 위치만 받아서 그린다(선택 처리는 화면 티켓 범위).
export function SelectionAction({ className, style, top, left, children = 'AI 설명', ...rest }: SelectionActionProps) {
  return (
    <Button
      variant="primary"
      className={cx(styles.action, className)}
      style={{ ...(top !== undefined ? { top } : null), ...(left !== undefined ? { left } : null), ...style }}
      {...rest}
    >
      {children}
    </Button>
  )
}
