import type { ComponentPropsWithRef, ReactNode } from 'react'
import styles from './QuizCard.module.css'
import { cx } from './cx.ts'

type QuizCardProps = {
  // 카드 맨 위 표시 줄(예: AiBadge, DifficultyChip)
  badges?: ReactNode
  // 문항 제목
  title?: ReactNode
  // 제목 단계. 화면 안에서 맞춘다(기본 h3).
  headingLevel?: 2 | 3
  // 제목 아래 본문(예: TextField)
  children?: ReactNode
  // 맨 아래 버튼 줄(예: 답하기 Button, 틀림 신고 Button)
  actions?: ReactNode
} & Omit<ComponentPropsWithRef<'section'>, 'children' | 'title'>

// 퀴즈 문항을 한 덩어리로 묶는 흰 종이 카드(디자인 시스템 README: 카드는 퀴즈 문항에만 쓴다).
// 표시 줄 → 제목 → 본문 → 버튼 줄 순서의 배치를 컴포넌트가 정하고, 안에 넣을 부품은 화면이 정한다.
export function QuizCard({ badges, title, headingLevel = 3, children, actions, className, ...rest }: QuizCardProps) {
  const Heading = headingLevel === 2 ? 'h2' : 'h3'
  return (
    <section className={cx(styles.card, className)} {...rest}>
      {badges ? <div className={styles.badges}>{badges}</div> : null}
      {title ? <Heading className={styles.title}>{title}</Heading> : null}
      {children}
      {actions ? <div className={styles.actions}>{actions}</div> : null}
    </section>
  )
}
