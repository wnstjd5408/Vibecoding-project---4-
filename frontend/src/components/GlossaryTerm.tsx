import type { ReactNode } from 'react'
import styles from './GlossaryTerm.module.css'

type GlossaryTermProps = {
  children: ReactNode
  // 있으면 누를 수 있는 용어(설명 시트를 연다). 없으면 시트 제목처럼 표시만 한다.
  onClick?: () => void
}

// 노트 본문 속 사전 용어. 글 흐름 안에 들어가는 인라인 요소다.
export function GlossaryTerm({ children, onClick }: GlossaryTermProps) {
  if (!onClick) return <span className={styles.term}>{children}</span>
  return (
    <button type="button" aria-haspopup="dialog" className={`${styles.term} ${styles.interactive}`} onClick={onClick}>
      {children}
    </button>
  )
}
