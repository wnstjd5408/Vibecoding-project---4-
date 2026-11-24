// 로그인 안내 시트 문구를 한곳에 모았다. 확정되면 이 파일만 고친다(MEG-77).
// "계정은 운영자가 만들어 줘요"는 결정 D-016(일반 사용자 계정은 운영자가 발급한다, 가입 기능 없음)과 맞는다.
import { AGENT_DISABLED_BY_BUILD } from '../agent/availability.ts'

export const LOGIN_PROMPT_MESSAGES = {
  // 제목은 상황과 관계없이 같다(디자인 시스템 BottomSheet 미리보기·목업 F2-2b와 같은 문구)
  title: '로그인이 필요해요',
  // 기본 본문: 캔버스 F2-2b·F3-2d. 노출 중단 플래그(VITE_CS_AGENT_DISABLED)가 켜진 빌드에서는 'AI에게 질문'이라는 이름을 보이지 않고
  // 그 빌드의 진입점인 'AI 설명'을 쓴다(MEG-241 결정 D2에서 넘겨받음, MEG-259).
  body: AGENT_DISABLED_BY_BUILD
    ? '로그인하면 AI 설명, 즐겨찾기, 오늘의 퀴즈를 쓸 수 있어요. 계정은 운영자가 만들어 줘요.'
    : '로그인하면 AI에게 질문, 즐겨찾기, 오늘의 퀴즈를 쓸 수 있어요. 계정은 운영자가 만들어 줘요.',
  // 상황별 본문: 호출하는 화면이 openLoginPrompt({ body })로 넘긴다. 목업 F1-1c(오늘의 퀴즈)
  quizBody: '오늘의 퀴즈는 로그인한 뒤에 볼 수 있어요. 계정은 운영자가 만들어 줘요.',
  login: '로그인',
} as const
