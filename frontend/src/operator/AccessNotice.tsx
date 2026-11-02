// 운영자 경로에서 쫓겨난 사람에게 이유를 알리는 팝업. 목업에 화면이 없어 모양은 F1-1c(로그인 안내 시트)를 따르고 문구는 모두 임시다(문구 미정, 확정되면 이 한 곳만 고친다).
import { useLocation, useNavigate } from 'react-router'
import { BottomSheet, LinkButton } from '../components/index.ts'
import { userPaths } from '../routes/paths.ts'
import { readAccessNotice } from './accessNotice.ts'
import type { AccessNoticeKind } from './accessNotice.ts'

const MESSAGES: Record<AccessNoticeKind, { title: string; body: string }> = {
  login_required: { title: '로그인이 필요해요', body: '운영자 화면은 운영자 계정으로 로그인한 뒤에 볼 수 있어요. 계정은 운영자가 만들어 줘요.' },
  operator_only: { title: '운영자만 쓸 수 있어요', body: '이 화면은 운영자 계정으로만 열 수 있어요.' },
}

export default function AccessNotice() {
  const location = useLocation()
  const navigate = useNavigate()
  const kind = readAccessNotice(location.state)
  // 닫을 때 안내 표시를 지워, 새로 고치거나 뒤로 가도 다시 뜨지 않게 한다.
  const close = () => navigate(`${location.pathname}${location.search}${location.hash}`, { replace: true, state: null })
  if (!kind) return null
  const message = MESSAGES[kind]
  return (
    <BottomSheet open onClose={close} title={message.title}>
      <p>{message.body}</p>
      {kind === 'login_required' ? (
        <LinkButton variant="primary" to={userPaths.login}>
          로그인
        </LinkButton>
      ) : null}
    </BottomSheet>
  )
}
