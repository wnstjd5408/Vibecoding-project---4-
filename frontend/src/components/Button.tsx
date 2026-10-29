import type { ComponentPropsWithRef, ReactNode } from 'react'
import { Link } from 'react-router'
import type { LinkProps } from 'react-router'
import styles from './Button.module.css'
import { cx } from './cx.ts'

// primary: 주요 동작(먹색 채움), outline: 보조 동작(테두리), report: 틀림 신고(빨간펜)
export type ButtonVariant = 'primary' | 'outline' | 'report'

type ButtonProps = { variant?: ButtonVariant; children: ReactNode } & Omit<ComponentPropsWithRef<'button'>, 'children'>

// 동작을 실행하는 버튼. type 기본값은 button이라 폼 안에서도 저절로 제출되지 않는다.
// aria-disabled="true"이면 모양만이 아니라 클릭도 막는다(disabled와 달리 포커스는 받는다).
export function Button({ variant = 'outline', className, type = 'button', onClick, children, ...rest }: ButtonProps) {
  const blocked = rest['aria-disabled'] === true || rest['aria-disabled'] === 'true'
  return (
    <button
      type={type}
      className={cx(styles.button, styles[variant], className)}
      onClick={blocked ? (event) => event.preventDefault() : onClick}
      {...rest}
    >
      {children}
    </button>
  )
}

type LinkButtonProps = { variant?: ButtonVariant; children: ReactNode } & Omit<LinkProps, 'children'>

// 다른 화면으로 가는 링크. 모양은 Button과 같다.
export function LinkButton({ variant = 'outline', className, children, ...rest }: LinkButtonProps) {
  return (
    <Link className={cx(styles.button, styles[variant], className)} {...rest}>
      {children}
    </Link>
  )
}
