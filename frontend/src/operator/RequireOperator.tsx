// 운영자 경로 보호. 화면에서 막는 것은 편의이고, 권한의 원본은 서버다(운영자 API는 403으로 막는다).
import { useState } from 'react'
import type { ReactNode } from 'react'
import { Navigate } from 'react-router'
import { Button, StateMessage } from '../components/index.ts'
import { useAuth } from '../auth/useAuth.ts'
import { userPaths } from '../routes/paths.ts'
import type { AccessNoticeState } from './accessNotice.ts'
import styles from './OperatorShell.module.css'

export default function RequireOperator({ children }: { children: ReactNode }) {
  const { status, role, refresh } = useAuth()
  const [wasOperator, setWasOperator] = useState(false)
  if (status === 'ready' && role === 'operator' && !wasOperator) setWasOperator(true)

  // 상태를 읽는 동안과 읽지 못했을 때는 방문자로 오해해 내보내지 않는다. 셸(메뉴)도 아직 보이지 않는다.
  if (status === 'loading') {
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
    // 이 화면을 운영자로 보다가 방문자가 됐다면 로그아웃이다(세션 만료와 구분하지 못한다). 스스로 한 일이므로 안내 없이 보낸다.
    if (role === 'visitor' && wasOperator) return <Navigate to={userPaths.noteList} replace />
    const state: AccessNoticeState = { accessNotice: role === 'visitor' ? 'login_required' : 'operator_only' }
    return <Navigate to={userPaths.noteList} replace state={state} />
  }
  return children
}
