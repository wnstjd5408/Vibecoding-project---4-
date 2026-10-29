import type { ComponentPropsWithRef, ReactNode } from 'react'
import styles from './TermLink.module.css'
import { cx } from './cx.ts'

type TermLinkProps = { children: ReactNode } & Omit<ComponentPropsWithRef<'a'>, 'children'>

// 노트 본문 속 사전 용어. 글 흐름 안에 들어가는 인라인 요소다.
// onClick이 있으면 누를 수 있는 용어이고 디자인 시스템 규칙대로 <a href aria-haspopup="dialog">로 그린다.
// 눌러도 주소는 바뀌지 않는다(preventDefault). 대신 onClick에서 설명 시트를 연다. href는 용어를 가리키는 해시(예: #dns)를 주면 된다.
// onClick이 없으면 시트 제목처럼 표시만 한다.
export function TermLink({ children, href = '#', onClick, className, ...rest }: TermLinkProps) {
  if (!onClick) return <span className={cx(styles.term, className)}>{children}</span>
  return (
    <a
      href={href}
      aria-haspopup="dialog"
      className={cx(styles.term, styles.interactive, className)}
      onClick={(event) => {
        event.preventDefault()
        onClick(event)
      }}
      {...rest}
    >
      {children}
    </a>
  )
}
