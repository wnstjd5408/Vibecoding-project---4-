import type { HTMLAttributes, ReactNode } from 'react'
import styles from './QuizCard.module.css'
import { cx } from './cx.ts'

type QuizCardProps = { children: ReactNode } & Omit<HTMLAttributes<HTMLElement>, 'children'>

// 퀴즈 문항을 한 덩어리로 묶는 흰 종이 카드(디자인 시스템 README: 카드는 퀴즈 문항에만 쓴다)
export function QuizCard({ className, children, ...rest }: QuizCardProps) {
  return (
    <section className={cx(styles.card, className)} {...rest}>
      {children}
    </section>
  )
}
