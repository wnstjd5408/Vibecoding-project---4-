import { Link } from 'react-router'
import styles from './NoteListItem.module.css'

type NoteListItemProps = {
  // 노트 읽기 화면 경로(예: noteReadPath(11))
  to: string
  title: string
  // 제목 아래 보조 줄. 예: "네트워크 · 2026-10-14"
  meta: string
}

// 노트 목록의 한 줄. 누르면 노트 읽기 화면으로 간다.
export function NoteListItem({ to, title, meta }: NoteListItemProps) {
  return (
    <Link to={to} className={styles.item}>
      <div className={styles.title}>{title}</div>
      <div className={styles.meta}>{meta}</div>
    </Link>
  )
}
