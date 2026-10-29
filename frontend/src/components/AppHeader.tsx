import type { ReactNode } from 'react'
import { Link } from 'react-router'
import styles from './AppHeader.module.css'

type AppHeaderProps = {
  // 제목형 헤더의 앱 이름. backTo가 있으면 쓰지 않는다.
  title?: string
  // 뒤로 가기형 헤더: 이동할 경로와 글자(기본 "목록")
  backTo?: string
  backLabel?: string
  // 오른쪽 자리. 로그인 버튼·계정 아이콘처럼 화면이 정한 조작을 넣는다(로그인 여부로 고르는 일은 화면이 한다).
  actions?: ReactNode
}

// 화면 맨 위 56px 띠. 모양만 맡고 로그인 상태 같은 화면 로직은 갖지 않는다.
export function AppHeader({ title, backTo, backLabel = '목록', actions }: AppHeaderProps) {
  return (
    <header className={styles.header}>
      {backTo ? (
        <Link to={backTo} className={styles.back}>
          {backLabel}
        </Link>
      ) : (
        <span className={styles.title}>{title}</span>
      )}
      <div className={styles.actions}>{actions}</div>
    </header>
  )
}
