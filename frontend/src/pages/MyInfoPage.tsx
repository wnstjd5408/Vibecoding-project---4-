// F4-5 내 정보(MEG-65). 로그인한 사용자의 표시 이름과 역할만 읽기 전용으로 보여 준다. 이메일은 MVP에서 뺐다.
import { Navigate, useLocation } from 'react-router'
import { AppHeader, Button, StateMessage } from '../components/index.ts'
import { useAuth } from '../auth/useAuth.ts'
import type { AuthRole } from '../auth/authContext.ts'
import { userPaths } from '../routes/paths.ts'
import styles from './MyInfoPage.module.css'

// 역할 표시. 서버 값(member·operator)을 목업 문구로 바꿔 보인다.
const ROLE_LABEL: Record<Exclude<AuthRole, 'visitor'>, string> = { member: '일반 사용자', operator: '운영자' }

// 계정 메뉴가 넘겨 준 "어디서 열었는지". 없거나 앱 안 경로가 아니면 과목·노트 목록으로 돌아간다.
function backPath(state: unknown): string {
  const from = (state as { from?: unknown } | null)?.from
  return typeof from === 'string' && from.startsWith('/') && !from.startsWith('//') ? from : userPaths.noteList
}

export default function MyInfoPage() {
  const location = useLocation()
  const { status, role, displayName, refresh } = useAuth()
  const back = backPath(location.state)

  // 상태를 읽는 동안과 읽지 못했을 때는 방문자로 오해해 로그인 화면으로 보내지 않는다.
  if (status === 'loading') {
    return (
      <div className={styles.page}>
        <AppHeader backTo={back} backLabel="돌아가기" />
        <main className={styles.main}>
          <StateMessage kind="loading" title="내 정보를 불러오는 중이에요" />
        </main>
      </div>
    )
  }
  if (status === 'error') {
    return (
      <div className={styles.page}>
        <AppHeader backTo={back} backLabel="돌아가기" />
        <main className={styles.main}>
          <StateMessage
            kind="error"
            title="내 정보를 불러오지 못했어요"
            description="잠시 뒤에 다시 시도해 주세요."
            action={<Button onClick={() => void refresh()}>다시 시도</Button>}
          />
        </main>
      </div>
    )
  }
  // 로그인하지 않았으면 내 정보가 없다. 로그인 화면으로 보낸다.
  if (role === 'visitor') return <Navigate to={userPaths.login} replace />

  return (
    <div className={styles.page}>
      <AppHeader backTo={back} backLabel="돌아가기" />
      <main className={styles.main}>
        <h1 className={styles.title}>내 정보</h1>
        <section aria-labelledby="my-info-account" className={styles.box}>
          <h2 id="my-info-account" className={styles.boxTitle}>
            계정
          </h2>
          <dl className={styles.details}>
            <dt>표시 이름</dt>
            <dd>{displayName ?? '-'}</dd>
            <dt>역할</dt>
            <dd>{ROLE_LABEL[role]}</dd>
          </dl>
        </section>
        <p className={styles.note}>운영자가 만든 계정 정보예요. 이 화면에서는 볼 수만 있어요.</p>
      </main>
    </div>
  )
}
