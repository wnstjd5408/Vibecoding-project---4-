// 운영자 경로 보호. 화면에서 막는 것은 편의이고, 권한의 원본은 서버다(운영자 API는 403으로 막는다).
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Navigate } from 'react-router'
import { Button, StateMessage } from '../components/index.ts'
import { clearExplicitLogout, isExplicitLogout } from '../auth/logoutIntent.ts'
import { useAuth } from '../auth/useAuth.ts'
import { userPaths } from '../routes/paths.ts'
import type { AccessNoticeState } from './accessNotice.ts'
import styles from './OperatorShell.module.css'

export default function RequireOperator({ children }: { children: ReactNode }) {
  const { status, role, refresh } = useAuth()
  // 이 경로에 들어올 때 이미 읽어 둔 로그인 상태가 있으면(앱 안 링크로 들어온 경우) 그 상태는 오래됐을 수 있다.
  // 다른 탭의 로그아웃이나 서버의 권한 회수가 반영되지 않았을 수 있으므로, 서버(E03)에 다시 확인한 뒤에 연다.
  // 처음 접속(새로 고침 포함)이면 앱이 시작하면서 이미 읽고 있으므로 다시 읽지 않는다.
  const [needsCheck] = useState(status === 'ready')
  const [checked, setChecked] = useState(false)
  useEffect(() => {
    if (!needsCheck) return
    let live = true
    void refresh().then(() => {
      if (live) setChecked(true)
    })
    return () => {
      live = false
    }
  }, [needsCheck, refresh])

  const [wasOperator, setWasOperator] = useState(false)
  if (status === 'ready' && role === 'operator' && !wasOperator) setWasOperator(true)
  // 운영자로 다시 확인됐으면 이전 로그아웃 표시는 필요 없다.
  useEffect(() => {
    if (role === 'operator' && (!needsCheck || checked)) clearExplicitLogout()
  }, [role, needsCheck, checked])

  // 상태를 읽는 동안과 읽지 못했을 때는 방문자로 오해해 내보내지 않는다. 셸(메뉴)도 아직 보이지 않는다.
  if (status === 'loading' || (needsCheck && !checked)) {
    return (
      <main className={styles.guard}>
        <StateMessage kind="loading" title="불러오는 중이에요" />
      </main>
    )
  }
  if (status === 'error') {
    return (
      <main className={styles.guard}>
        <StateMessage
          kind="error"
          title="로그인 상태를 불러오지 못했어요"
          description="잠시 뒤에 다시 시도해 주세요."
          action={<Button onClick={() => void refresh()}>다시 시도</Button>}
        />
      </main>
    )
  }
  // 운영자가 아니면 기본 접속 화면으로 보내고, 이유는 그 화면 위 팝업으로 알린다(AccessNotice).
  if (role === 'visitor' || role === 'member') {
    // 이 화면을 운영자로 보다가 직접 로그아웃해서 방문자가 된 경우만 안내 없이 보낸다. 세션 만료·권한 회수는 안내한다.
    if (role === 'visitor' && wasOperator && isExplicitLogout()) return <Navigate to={userPaths.noteList} replace />
    const state: AccessNoticeState = { accessNotice: role === 'visitor' ? 'login_required' : 'operator_only' }
    return <Navigate to={userPaths.noteList} replace state={state} />
  }
  return children
}
