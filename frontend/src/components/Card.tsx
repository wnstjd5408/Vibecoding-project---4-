import type { HTMLAttributes, ReactNode } from 'react'
import styles from './Card.module.css'
import { cx } from './cx.ts'

type CardProps = { children: ReactNode } & Omit<HTMLAttributes<HTMLElement>, 'children'>

// 퀴즈 문항·안내처럼 한 덩어리로 묶는 흰 종이 카드
export function Card({ className, children, ...rest }: CardProps) {
  return (
    <section className={cx(styles.card, className)} {...rest}>
      {children}
    </section>
  )
}
