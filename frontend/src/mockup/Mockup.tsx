import { useEffect, useState } from 'react'
import { Link, Outlet, useParams, useSearchParams } from 'react-router'
import { AdminPage } from './AdminPages.tsx'
import { MobilePage } from './MobilePages.tsx'
import { usePreview } from './model.ts'
import { PreviewProvider } from './PreviewProvider.tsx'
import { isOperatorScreen, isScreenId, previewPath, screens } from './screens.ts'
import { Button } from './ui.tsx'
import styles from './mockup.module.css'

function Notice() {
  const { notice, setNotice } = usePreview()
  useEffect(() => { if (!notice) return; const timer = window.setTimeout(() => setNotice(''), 4000); return () => window.clearTimeout(timer) }, [notice, setNotice])
  return notice ? <div className={styles.toast} role="status">{notice}</div> : null
}

export function MockupLayout() {
  const [query] = useSearchParams()
  return <PreviewProvider><div className={styles.scope} data-theme={query.get('theme') === 'dark' ? 'dark' : 'light'}><Outlet /><Notice /></div></PreviewProvider>
}

export function MockupCatalog() {
  const [filter, setFilter] = useState<'all' | 'mobile' | 'admin'>('all')
  const [dark, setDark] = useState(false)
  return <main className={styles.catalog}><div className={styles.stack}><h1>CS 학습 노트 · 목업 v0.2</h1>
    <p>디자인 검토가 완료된 31개 화면과 상태를 확인할 수 있어요.</p>
    <p className={styles.muted}>검토용 미리보기입니다. 입력과 변경은 이 탭의 메모리에만 남고 새로고침하면 초기화됩니다. 실제 로그인, 계정 발급, AI 생성, 파일 업로드는 수행하지 않습니다. 실제 계정 정보를 입력하지 마세요.</p>
    <p className={styles.muted}>합성 로그인: member@example.test 또는 operator@example.test / example-password</p>
    <div className={styles.row}>{([['all', '전체 31개'], ['mobile', '사용자 19개'], ['admin', '운영자 12개']] as const).map(([value, label]) => <Button key={value} className={styles.chip} aria-pressed={filter === value} onClick={() => setFilter(value)}>{label}</Button>)}<label className={styles.checkChip}><input type="checkbox" checked={dark} onChange={(event) => setDark(event.target.checked)} />어두운 테마</label></div>
    <Link to="/dev/foundation">기존 프런트 공통 기반 확인</Link>
  </div><div className={styles.catalogGrid}>{screens.filter(([id]) => filter === 'all' || (filter === 'admin') === isOperatorScreen(id)).map(([id, name, state]) => <Link key={id} className={styles.card} to={`${previewPath(id)}${dark ? '?theme=dark' : ''}`}><span className={styles.hint}>{id} · {isOperatorScreen(id) ? 'PC' : '모바일'}</span><h3>{name}</h3><span className={styles.muted}>{state}</span></Link>)}</div></main>
}

export function MockupScreen() {
  const { screenId = '' } = useParams()
  const [query] = useSearchParams()
  useEffect(() => {
    const previous = document.title
    const screen = screens.find(([id]) => id === screenId)
    document.title = screen ? `${screen[1]} · CS 학습 노트` : '화면을 찾을 수 없어요'
    return () => { document.title = previous }
  }, [screenId])
  if (!isScreenId(screenId)) return <main className={styles.catalog}><h1>화면을 찾을 수 없어요</h1><Link to="/dev/mockup">전체 화면 보기</Link></main>
  return <>{isOperatorScreen(screenId) ? <AdminPage key={screenId} id={screenId} /> : <MobilePage key={screenId} id={screenId} />}{query.get('clean') !== 'true' && <Link className={styles.reviewLink} to="/dev/mockup">전체 화면 · {screenId}</Link>}</>
}
