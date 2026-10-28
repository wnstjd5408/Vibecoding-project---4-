import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Link } from 'react-router'
import styles from './Button.module.css'
import { cx } from './cx.ts'

// primary: 주요 동작(먹색 채움), outline: 보조 동작(테두리), report: 틀림 신고(빨간펜)
export type ButtonVariant = 'primary' | 'outline' | 'report'

type ButtonProps = { variant?: ButtonVariant; children: ReactNode } & Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'>

// 동작을 실행하는 버튼. type 기본값은 button이라 폼 안에서도 저절로 제출되지 않는다.
export function Button({ variant = 'outline', className, type = 'button', children, ...rest }: ButtonProps) {
  return (
    <button type={type} className={cx(styles.button, styles[variant], className)} {...rest}>
      {children}
    </button>
  )
}

type LinkButtonProps = { to: string; variant?: ButtonVariant; className?: string; children: ReactNode }

// 다른 화면으로 가는 링크. 모양은 Button과 같다.
export function LinkButton({ to, variant = 'outline', className, children }: LinkButtonProps) {
  return (
    <Link to={to} className={cx(styles.button, styles[variant], className)}>
      {children}
    </Link>
  )
}
