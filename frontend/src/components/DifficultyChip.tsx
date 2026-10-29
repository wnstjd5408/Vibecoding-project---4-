import styles from './DifficultyChip.module.css'

// 퀴즈 난이도(하·중·상). 서버가 주는 난이도 값에 맞춰 화면에서 이 칩을 고른다.
export type Difficulty = 'low' | 'mid' | 'high'

const LABEL: Record<Difficulty, string> = { low: '난이도 하', mid: '난이도 중', high: '난이도 상' }

export function DifficultyChip({ level }: { level: Difficulty }) {
  return <span className={`${styles.chip} ${styles[level]}`}>{LABEL[level]}</span>
}
