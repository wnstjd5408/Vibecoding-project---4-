import { AppHeader, LinkButton } from '../components/index.ts'
import { AccountMenu } from '../account/AccountMenu.tsx'
import { useAuth } from '../auth/useAuth.ts'
import { userPaths } from '../routes/paths.ts'
import DevNav from './DevNav.tsx'

// 아직 없는 화면을 잠시 대신하는 빈 페이지. 해당 티켓이 화면을 만들 때 이 페이지를 교체한다.
// withHeader가 true인 사용자(모바일) 화면은 앱 헤더를 임시로 단다. 로그인 상태면 계정 메뉴(F4-4), 방문자면 로그인 버튼이다.
// 이 헤더는 로그인·로그아웃 흐름을 눈으로 확인하려는 것이고, 화면 티켓이 자기 헤더를 만들면 이 페이지와 함께 사라진다.
export default function Placeholder({
  screenId,
  title,
  ticket,
  withHeader = false,
}: {
  screenId: string
  title: string
  ticket: string
  withHeader?: boolean
}) {
  const { status, role } = useAuth()
  const actions =
    status === 'loading' ? null : role === 'visitor' ? <LinkButton to={userPaths.login}>로그인</LinkButton> : <AccountMenu />
  return (
    <>
      {withHeader ? <AppHeader title="CS 학습 노트" actions={actions} /> : null}
      <main style={{ padding: '2rem' }}>
        <h1>
          {screenId} {title}
        </h1>
        <p>
          임시 빈 페이지입니다. 이 화면은 {ticket}에서 만듭니다.
        </p>
        <DevNav />
      </main>
    </>
  )
}
