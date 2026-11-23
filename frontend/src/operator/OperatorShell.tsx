// 운영자(PC) 화면 공통 틀(MEG-78). 목업 v0.2 F5 계열의 헤더·왼쪽 메뉴·본문 영역이다. 개별 화면은 Outlet 자리에 들어오고 각자 <main>을 갖는다.
import { Link, Outlet, useLocation } from 'react-router'
import { AccountMenu } from '../account/AccountMenu.tsx'
import { Badge } from '../components/Badge.tsx'
import { operatorPaths, userPaths } from '../routes/paths.ts'
import RequireOperator from './RequireOperator.tsx'
import styles from './OperatorShell.module.css'

// 메뉴. 하위 화면(노트 수정 등)에서도 해당 메뉴가 선택된 채로 보이도록 경로 앞부분으로 맞춘다.
const NAV: { label: string; to: string; active: (pathname: string) => boolean }[] = [
  { label: '노트', to: operatorPaths.home, active: (p) => p === operatorPaths.home || p.startsWith(`${operatorPaths.home}/notes`) },
  { label: '용어 사전', to: operatorPaths.glossary, active: (p) => p.startsWith(operatorPaths.glossary) },
  { label: '신고', to: operatorPaths.reports, active: (p) => p.startsWith(operatorPaths.reports) },
  { label: '계정 발급', to: operatorPaths.accounts, active: (p) => p.startsWith(operatorPaths.accounts) },
]

export default function OperatorShell() {
  return (
    <RequireOperator>
      <Shell />
    </RequireOperator>
  )
}

function Shell() {
  const { pathname } = useLocation()
  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <div className={styles.brand}>
          <span className={styles.title}>CS 학습 노트</span>
          <Badge>운영자</Badge>
        </div>
        {/* 사용자 과목·노트 목록(F1-1b)으로 가는 링크(MEG-269). 그 화면의 "운영자 메뉴" 링크와 짝을 이룬다. */}
        <div className={styles.actions}>
          <Link className={styles.headerLink} to={userPaths.noteList}>노트 목록 보기</Link>
          <AccountMenu myInfoPath={operatorPaths.myInfo} />
        </div>
      </header>
      <div className={styles.body}>
        <nav className={styles.sidebar} aria-label="운영자 메뉴">
          {NAV.map((item) => (
            <Link key={item.to} to={item.to} className={styles.navItem} aria-current={item.active(pathname) ? 'page' : undefined}>
              {item.label}
            </Link>
          ))}
        </nav>
        <div className={styles.content}>
          <Outlet />
        </div>
      </div>
    </div>
  )
}
