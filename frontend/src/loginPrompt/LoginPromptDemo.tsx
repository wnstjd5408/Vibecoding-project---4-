import { useState } from 'react'
import { apiFetch } from '../api/client.ts'
import type { FavoriteResponse } from '../api/types.ts'
import { Button } from '../components/Button.tsx'
import { FavoriteToggle } from '../components/FavoriteToggle.tsx'
import { LOGIN_PROMPT_MESSAGES } from './messages.ts'
import { useLoginPrompt } from './useLoginPrompt.ts'

// /dev/components 쇼케이스에서 로그인 안내 시트의 공통 처리를 확인하는 데모(MEG-77). 제품 화면이 아니다.
// 실제 즐겨찾기·AI 설명 화면은 MEG-76·90·106이 만들고, 거기서도 아래와 같이 handleLoginRequired를 쓴다.

const MESSAGES = {
  saved: '즐겨찾기에 저장했어요',
  removed: '즐겨찾기를 해제했어요',
  failed: '즐겨찾기를 저장하지 못했어요',
  aiFailed: 'AI 설명을 불러오지 못했어요',
}

// 가짜 응답의 E08은 방문자에게 401 login_required를 준다. 그때는 시트가 열리고, 눌림 상태와 저장 성공 표시는 남지 않는다.
export function FavoriteDemo() {
  const { handleLoginRequired } = useLoginPrompt()
  const [pressed, setPressed] = useState(false)
  const [status, setStatus] = useState('')

  async function change(next: boolean) {
    setStatus('')
    try {
      const response = await apiFetch<FavoriteResponse>('/api/favorites/7', { method: 'PUT', body: { favorited: next } })
      setPressed(response.is_favorite)
      setStatus(response.is_favorite ? MESSAGES.saved : MESSAGES.removed)
    } catch (error) {
      // 401 login_required는 시트로 안내하고, 그 밖의 오류는 이 화면의 기존 오류 처리로 둔다.
      if (!handleLoginRequired(error)) setStatus(MESSAGES.failed)
    }
  }

  return (
    <>
      <FavoriteToggle pressed={pressed} onPressedChange={change} />
      <p role="status" data-testid="favorite-status" style={{ margin: 0, fontSize: 14, lineHeight: '22px' }}>{status}</p>
    </>
  )
}

// E09(AI 설명)도 방문자에게 401 login_required다. 같은 handleLoginRequired로 같은 시트를 띄운다.
export function AiExplainDemo() {
  const { handleLoginRequired } = useLoginPrompt()
  const [status, setStatus] = useState('')

  async function explain() {
    setStatus('')
    try {
      await apiFetch('/api/ai/explanations', { method: 'POST' })
    } catch (error) {
      if (!handleLoginRequired(error)) setStatus(MESSAGES.aiFailed)
    }
  }

  return (
    <>
      <Button onClick={explain}>AI 설명</Button>
      <p role="status" data-testid="ai-status" style={{ margin: 0, fontSize: 14, lineHeight: '22px' }}>{status}</p>
    </>
  )
}

// 상황별 본문을 넘겨 여는 예(오늘의 퀴즈). 닫은 뒤 기본 호출을 하면 이전 문구가 남지 않는다.
export function QuizPromptDemo() {
  const { openLoginPrompt } = useLoginPrompt()
  return (
    <>
      <Button onClick={() => openLoginPrompt({ body: LOGIN_PROMPT_MESSAGES.quizBody })}>퀴즈 문구로 열기</Button>
      <Button onClick={() => openLoginPrompt()}>기본 문구로 열기</Button>
    </>
  )
}
