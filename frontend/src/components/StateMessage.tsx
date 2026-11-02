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
  // 화면 안에서 제목 단계를 맞춘다. 디자인 시스템 기본은 h3.
  headingLevel?: 2 | 3
}

// 로딩·빈 상태·오류 안내. 불러오는 중은 status, 오류는 alert로 알려 스크린 리더가 바로 읽는다.
// 오류 제목에는 "오류:"를 자동으로 붙인다(색이 아니라 글자로 알리기 위해). 제목에 따로 쓰지 않는다.
export function StateMessage({ kind, title, description, action, headingLevel = 3 }: StateMessageProps) {
  const role = kind === 'error' ? 'alert' : kind === 'loading' ? 'status' : undefined
  const Heading = headingLevel === 2 ? 'h2' : 'h3'
  return (
    <section
      className={styles.box}
      role={role}
      aria-live={kind === 'loading' ? 'polite' : undefined}
    >
      <Heading className={styles.title}>
        {kind === 'error' ? '오류: ' : ''}
        {title}
      </Heading>
      {description ? <p className={styles.description}>{description}</p> : null}
      {kind === 'loading' ? (
        <div className={styles.bars} aria-hidden="true">
          <span className={styles.bar} />
          <span className={styles.bar} />
          <span className={styles.bar} />
        </div>
      ) : null}
      {action ? <div className={styles.action}>{action}</div> : null}
    </section>
  )
}
