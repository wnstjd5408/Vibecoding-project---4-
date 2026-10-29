import type { ReactNode } from 'react'
import styles from './StateMessage.module.css'

// loading: 불러오는 중, empty: 보여 줄 것이 없음, error: 실패
export type StateKind = 'loading' | 'empty' | 'error'

type StateMessageProps = {
  kind: StateKind
  title: string
  description?: string
  // 다음 행동 버튼·링크(예: "노트 보러 가기", "다시 시도")
  action?: ReactNode
}

// 로딩·빈 상태·오류 안내. 불러오는 중은 status, 오류는 alert로 알려 스크린 리더가 바로 읽는다.
export function StateMessage({ kind, title, description, action }: StateMessageProps) {
  const role = kind === 'error' ? 'alert' : kind === 'loading' ? 'status' : undefined
  return (
    <section className={styles.box} role={role} aria-busy={kind === 'loading' ? true : undefined}>
      <h2 className={styles.title}>{title}</h2>
      {description ? <p className={styles.description}>{description}</p> : null}
      {action ? <div className={styles.action}>{action}</div> : null}
    </section>
  )
}
