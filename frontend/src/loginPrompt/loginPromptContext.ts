import { createContext } from 'react'

export type LoginPromptOptions = {
  // 상황별 본문(예: 오늘의 퀴즈). 없으면 기본 본문이다. 호출마다 정해지며 이전 호출의 문구는 남지 않는다.
  body?: string
  // PC 폭(1024px 이상)에서 오른쪽 사이드 패널로 열지. 용어 즐겨찾기의 E08 401(F3-2d)만 true다. 그 밖의 안내는 PC 폭에서도 바텀시트다.
  panel?: boolean
  // PC 패널을 닫을 때 포커스를 돌려줄 요소(예: 마지막으로 누른 용어 링크)
  returnFocus?: () => HTMLElement | null
}

export type LoginPromptContextValue = {
  // 로그인 안내 시트를 연다. 화면이 방문자라는 것을 이미 알 때 쓴다(예: 방문자의 "오늘의 퀴즈" 클릭).
  openLoginPrompt: (options?: LoginPromptOptions) => void
  // API 오류가 401 login_required이면 시트를 열고 true를 돌려준다. 그 밖의 오류는 false라 호출한 화면이 기존 오류 처리를 이어 간다.
  handleLoginRequired: (error: unknown, options?: LoginPromptOptions) => boolean
  // 열려 있는 로그인 안내를 닫는다. 같은 자리의 다른 패널(용어·AI 설명)이 열릴 때 가려지지 않게 화면이 쓴다.
  closeLoginPrompt: () => void
  // 로그인 안내가 PC 사이드 패널로 열려 있는지. 화면이 본문 오른쪽 480px를 비워 두는 데 쓴다.
  panelOpen: boolean
}

export const LoginPromptContext = createContext<LoginPromptContextValue | null>(null)
