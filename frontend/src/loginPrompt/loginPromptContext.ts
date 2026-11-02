import { createContext } from 'react'

export type LoginPromptOptions = {
  // 상황별 본문(예: 오늘의 퀴즈). 없으면 기본 본문이다. 호출마다 정해지며 이전 호출의 문구는 남지 않는다.
  body?: string
}

export type LoginPromptContextValue = {
  // 로그인 안내 시트를 연다. 화면이 방문자라는 것을 이미 알 때 쓴다(예: 방문자의 "오늘의 퀴즈" 클릭).
  openLoginPrompt: (options?: LoginPromptOptions) => void
  // API 오류가 401 login_required이면 시트를 열고 true를 돌려준다. 그 밖의 오류는 false라 호출한 화면이 기존 오류 처리를 이어 간다.
  handleLoginRequired: (error: unknown, options?: LoginPromptOptions) => boolean
}

export const LoginPromptContext = createContext<LoginPromptContextValue | null>(null)
