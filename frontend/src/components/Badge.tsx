import type { ReactNode } from 'react'
import styles from './Badge.module.css'
import { cx } from './cx.ts'

// ai: "AI 생성" 표시(연필), dictionary: "사전" 표시
export type BadgeTone = 'ai' | 'dictionary'

type BadgeProps = { tone?: BadgeTone; className?: string; children: ReactNode }

export function Badge({ tone = 'dictionary', className, children }: BadgeProps) {
  return <span className={cx(styles.badge, styles[tone], className)}>{children}</span>
}
