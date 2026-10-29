import { useId } from 'react'
import type { InputHTMLAttributes, TextareaHTMLAttributes } from 'react'
import styles from './TextField.module.css'

type BaseProps = {
  label: string
  // 입력 방법 등 미리 알려 줄 안내
  hint?: string
  // 오류 문구. 있으면 "오류:"를 붙여 입력 칸 아래에 알리고 aria-invalid로 표시한다.
  error?: string
}
type InputTextFieldProps = BaseProps & { multiline?: false } & Omit<InputHTMLAttributes<HTMLInputElement>, 'id'>
type TextAreaTextFieldProps = BaseProps & { multiline: true } & Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'id'>

// 라벨이 붙은 입력 칸. multiline이 true면 여러 줄 입력(textarea)이다. 라벨·안내·오류는 id로 입력과 이어진다.
export function TextField(props: InputTextFieldProps | TextAreaTextFieldProps) {
  const id = useId()
  const hintId = `${id}-hint`
  const errorId = `${id}-error`
  const { label, hint, error, multiline, ...rest } = props
  const describedBy = [rest['aria-describedby'], hint ? hintId : null, error ? errorId : null].filter(Boolean).join(' ') || undefined
  const common = {
    id,
    className: styles.control,
    'aria-invalid': error ? true : undefined,
    'aria-describedby': describedBy,
  }
  return (
    <div>
      <label htmlFor={id} className={styles.label}>
        {label}
      </label>
      {multiline ? (
        <textarea {...(rest as TextareaHTMLAttributes<HTMLTextAreaElement>)} {...common} />
      ) : (
        <input {...(rest as InputHTMLAttributes<HTMLInputElement>)} {...common} />
      )}
      {hint ? (
        <p id={hintId} className={styles.hint}>
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} role="alert" className={styles.error}>
          오류: {error}
        </p>
      ) : null}
    </div>
  )
}
