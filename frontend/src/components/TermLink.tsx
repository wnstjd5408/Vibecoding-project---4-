import type { ComponentPropsWithRef, ReactNode } from 'react'
import styles from './TermLink.module.css'
import { cx } from './cx.ts'

type TermLinkProps = { children: ReactNode } & Omit<ComponentPropsWithRef<'button'>, 'children' | 'type'>

// 노트 본문 속 사전 용어. 글 흐름 안에 들어가는 인라인 요소다.
// onClick이 있으면 누를 수 있는 용어(설명 시트를 연다)이고 button으로 그린다. 시트를 여는 동작이라 a가 아니라 button이다.
// 없으면 시트 제목처럼 표시만 한다.
export function TermLink({ children, onClick, className, ...rest }: TermLinkProps) {
  if (!onClick) return <span className={cx(styles.term, className)}>{children}</span>
  return (
    <button
      type="button"
      aria-haspopup="dialog"
      className={cx(styles.term, styles.interactive, className)}
      onClick={onClick}
      {...rest}
    >
      {children}
    </button>
  )
}
