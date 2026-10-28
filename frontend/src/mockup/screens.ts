// The 31 named frames in the approved v0.2 export, in their original order.
export const screens = [
  ['F1-1', '과목·노트 목록', '기본'],
  ['F1-2', '노트 읽기', '기본'],
  ['F1-3', '용어 바텀시트', '사전·비로그인'],
  ['F2-1', '단어 선택', 'AI 설명 버튼'],
  ['F1-3c', '용어 전체 화면', '사전·즐겨찾기함'],
  ['F1-3b', '용어 전체 화면', '사전'],
  ['F1-1b', '과목·노트 목록', '로그인·운영자'],
  ['F1-1c', '로그인 안내 시트', '비로그인·오늘의 퀴즈'],
  ['F2-2a', 'AI 설명 시트', 'AI 생성·로그인'],
  ['F2-2b', '로그인 안내 시트', '비로그인'],
  ['F4-1', '로그인', '기본'],
  ['F3-2', '즐겨찾기 저장됨', '사전·로그인'],
  ['F2-2c', 'AI 설명 전체 화면', 'AI 생성·로그인'],
  ['F3-3a', '퀴즈 문항', '기본'],
  ['F3-4', '정답·해설', 'AI 생성'],
  ['F3-5', '꼬리 질문 1/2', '채점 없음'],
  ['F3-3b', '퀴즈 없음', '빈 상태'],
  ['F4-4', '계정 메뉴 열림', '사용자'],
  ['F4-5', '내 정보', '사용자·읽기 전용'],
  ['F4-3a', '계정 발급', '운영자'],
  ['F4-3b', '계정 발급 완료', '비밀번호 비표시'],
  ['F4-3c', '계정 메뉴 열림', '운영자'],
  ['F4-3d', '내 정보', '운영자·읽기 전용'],
  ['F5-1a', '노트 목록', '운영자'],
  ['F5-1b', '노트 수정', 'AI 설명 무효 안내'],
  ['F5-1c', '용어 사전 편집', '운영자'],
  ['F5-1d', '새 노트', '빈 폼'],
  ['F5-1e', '새 용어', '빈 폼'],
  ['F5-1f', '노트 삭제 확인', '문구 미정'],
  ['F5-2', '신고 목록', '열림'],
  ['F5-3', '사전에 바른 설명 넣기', '신고에서 진입'],
] as const

export type ScreenId = typeof screens[number][0]
export const previewPath = (id: ScreenId) => `/dev/mockup/${id}`
export const isOperatorScreen = (id: ScreenId) => id.startsWith('F5-') || id.startsWith('F4-3')
export const isScreenId = (id: string): id is ScreenId => screens.some(([key]) => key === id)

export function frameViewport(id: ScreenId) {
  if (!isOperatorScreen(id)) return { width: 390, height: 844 }
  const heights: Partial<Record<ScreenId, number>> = { 'F5-1b': 1040, 'F5-1c': 840, 'F5-1d': 960, 'F5-1e': 760, 'F5-3': 820 }
  return { width: 1280, height: heights[id] ?? 720 }
}
