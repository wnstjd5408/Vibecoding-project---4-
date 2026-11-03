import type { ReactNode } from 'react'
import { Link } from 'react-router'
import styles from './AppHeader.module.css'
import { cx } from './cx.ts'

type AppHeaderProps = {
  // 제목형 헤더의 앱 이름. backTo와 함께 주면 PC 폭(1024px 이상)에서만 "앱 이름 + 뒤로 가기"로 함께 보인다.
  title?: string
  // 뒤로 가기형 헤더: 이동할 경로와 글자(기본 "목록")
  backTo?: string
  backLabel?: string
  // 오른쪽 자리. 로그인 버튼·계정 아이콘처럼 화면이 정한 조작을 넣는다(로그인 여부로 고르는 일은 화면이 한다).
  actions?: ReactNode
  // PC 폭에서 헤더를 화면 전체 폭으로 펴고 좌우 여백을 넓힌다(노트 목록·노트 읽기 PC 배치). 모바일은 그대로다.
  wide?: boolean
  // PC 폭에서 헤더를 화면 위에 고정한다(노트 읽기 PC 배치). 다른 화면으로 넓히지 않는다.
  stickyOnWide?: boolean
}

// 화면 맨 위 56px 띠. 모양만 맡고 로그인 상태 같은 화면 로직은 갖지 않는다.
export function AppHeader({ title, backTo, backLabel = '목록', actions, wide = false, stickyOnWide = false }: AppHeaderProps) {
  return (
    <header className={cx(styles.header, wide && styles.wide, stickyOnWide && styles.stickyOnWide)}>
      <div className={styles.lead}>
        {title && (!backTo || wide) ? <span className={cx(styles.title, backTo && styles.titleBesideBack)}>{title}</span> : null}
        {backTo ? (
          <Link to={backTo} className={styles.back}>
            {backLabel}
          </Link>
        ) : null}
      </div>
      <div className={styles.actions}>{actions}</div>
    </header>
  )
}
