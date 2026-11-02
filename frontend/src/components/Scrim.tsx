import styles from './Scrim.module.css'
import { cx } from './cx.ts'

type ScrimProps = {
  // 막을 눌렀을 때(시트 닫기 등)
  onClick?: () => void
  // true면 화면(뷰포트) 전체를 덮는다. 기본값은 가장 가까운 position 기준 부모를 덮는다.
  fixed?: boolean
}

export function Scrim({ onClick, fixed = false }: ScrimProps) {
  return <div aria-hidden="true" className={cx(styles.scrim, fixed && styles.fixed)} onClick={onClick} />
}
