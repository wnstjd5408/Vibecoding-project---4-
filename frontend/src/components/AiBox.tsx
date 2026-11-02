import type { ReactNode } from 'react'
import styles from './AiBox.module.css'

type AiBoxProps = {
  // 스크린 리더가 읽는 이름. 예: "AI 생성 설명", "AI 생성 정답과 해설"
  label: string
  children: ReactNode
}

// AI가 만든 내용을 보여 주는 상자. 사람이 쓴 내용과 구분되도록 항상 "AI 생성" 배지와 함께 쓴다.
export function AiBox({ label, children }: AiBoxProps) {
  return (
    <div role="group" aria-label={label} className={styles.box}>
      {children}
    </div>
  )
}
