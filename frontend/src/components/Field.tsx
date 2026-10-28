import { useId } from 'react'
import type { InputHTMLAttributes, TextareaHTMLAttributes } from 'react'
import styles from './Field.module.css'

type BaseProps = { label: string }
type InputFieldProps = BaseProps & { multiline?: false } & Omit<InputHTMLAttributes<HTMLInputElement>, 'id'>
type TextAreaFieldProps = BaseProps & { multiline: true } & Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'id'>

// 라벨이 붙은 입력 칸. multiline이 true면 여러 줄 입력(textarea)이다. 라벨과 입력은 id로 이어진다.
export function Field(props: InputFieldProps | TextAreaFieldProps) {
  const id = useId()
  if (props.multiline) {
    const { label, multiline, ...rest } = props
    void multiline
    return (
      <div>
        <label htmlFor={id} className={styles.label}>
          {label}
        </label>
        <textarea id={id} className={styles.control} {...rest} />
      </div>
    )
  }
  const { label, multiline, ...rest } = props
  void multiline
  return (
    <div>
      <label htmlFor={id} className={styles.label}>
        {label}
      </label>
      <input id={id} className={styles.control} {...rest} />
    </div>
  )
}
