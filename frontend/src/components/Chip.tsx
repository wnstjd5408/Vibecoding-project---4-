import type { ButtonHTMLAttributes, ReactNode } from 'react'
import styles from './Chip.module.css'
import { cx } from './cx.ts'

type ChipProps = { selected: boolean; children: ReactNode } & Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children' | 'aria-pressed'>

// 과목 선택 같은 알약 모양 선택 버튼. 선택 여부는 색과 aria-pressed로 함께 알린다.
export function Chip({ selected, className, type = 'button', children, ...rest }: ChipProps) {
  return (
    <button type={type} aria-pressed={selected} className={cx(styles.chip, className)} {...rest}>
      {children}
    </button>
  )
}
