import { useEffect, useId, useRef } from 'react'
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from 'react'
import styles from './mockup.module.css'

export function Button({ variant = 'outline', className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'outline' | 'solid' | 'danger' | 'text' }) {
  return <button type="button" className={`${styles.button} ${styles[variant]} ${className}`} {...props} />
}

// Paths copied from the supplied design, not a new icon set.
export function Icon({ name }: { name: 'account' | 'star' | 'expand' | 'report' | 'plus' }) {
  return <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    {name === 'account' && <><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8" /></>}
    {name === 'star' && <path d="M12 3.5l2.6 5.3 5.9.9-4.25 4.15 1 5.85L12 16.9l-5.25 2.8 1-5.85L3.5 9.7l5.9-.9L12 3.5z" />}
    {name === 'expand' && <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />}
    {name === 'report' && <><path d="M4 21V3m0 1h14l-3 5 3 5H4" /></>}
    {name === 'plus' && <path d="M12 5v14M5 12h14" />}
  </svg>
}

export function IconButton({ icon, label, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { icon: Parameters<typeof Icon>[0]['name']; label: string; variant?: 'outline' | 'solid' | 'danger' | 'text' }) {
  return <Button {...props} aria-label={label} className={styles.iconButton}><Icon name={icon} /></Button>
}
export function Badge({ children, difficulty = false }: { children: ReactNode; difficulty?: boolean }) {
  return <span className={`${styles.badge} ${difficulty ? styles.difficulty : ''}`}>{children}</span>
}
export function Field({ label, hint, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string }) {
  const id = useId()
  return <div><label className={styles.label} htmlFor={id}>{label}</label><input id={id} className={styles.input} aria-describedby={hint ? `${id}-hint` : undefined} {...props} />{hint && <p className={styles.hint} id={`${id}-hint`}>{hint}</p>}</div>
}
export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`${styles.card} ${className}`}>{children}</div>
}
export function ImagePlaceholder() {
  return <div className={styles.imagePlaceholder}>이미지 자리</div>
}
export function Dialog({ title, children, close, centered = false }: { title: string; children: ReactNode; close: () => void; centered?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null)
  const id = useId()
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const dialog = ref.current!
    dialog.showModal()
    dialog.focus({ preventScroll: true })
    return () => { dialog.close(); previous?.focus() }
  }, [])
  return <dialog ref={ref} tabIndex={-1} autoFocus aria-labelledby={id} className={`${styles.dialog} ${centered ? styles.centered : ''}`} onCancel={(event) => { event.preventDefault(); close() }} onClick={(event) => { if (event.target === event.currentTarget) close() }}>
    <div className={styles.dialogContent} onClick={(event) => event.stopPropagation()}>
      {!centered && <div className={styles.handleRow}><span className={styles.handle} /><Button variant="text" className={styles.close} onClick={close}>닫기</Button></div>}
      <span className={styles.srOnly} id={id}>{title}</span>{children}
    </div>
  </dialog>
}
