import type { ComponentPropsWithRef, ReactNode } from 'react'
import { Link } from 'react-router'
import { cx } from './cx.ts'
import styles from './IconButton.module.css'

// 아이콘만 있는 버튼은 글자 라벨이 없으므로 label(aria-label)이 필수다(목업 구현 메모).
type IconButtonProps = { label: string; children: ReactNode } & Omit<ComponentPropsWithRef<'button'>, 'children' | 'aria-label'>

export function IconButton({ label, className, type = 'button', children, ...rest }: IconButtonProps) {
  return (
    <button type={type} aria-label={label} className={cx(styles.icon, className)} {...rest}>
      {children}
    </button>
  )
}

type IconLinkButtonProps = { label: string; to: string; className?: string; children: ReactNode }

// 다른 화면으로 가는 아이콘 링크(예: 전체 보기)
export function IconLinkButton({ label, to, className, children }: IconLinkButtonProps) {
  return (
    <Link to={to} aria-label={label} className={cx(styles.icon, className)}>
      {children}
    </Link>
  )
}
