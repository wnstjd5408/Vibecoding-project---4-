// 화면 경로. 이름 옆 번호는 목업 v0.2의 화면 ID다. 화면 티켓은 여기 경로를 그대로 쓴다.
// 사용자(모바일) 화면과 운영자(PC) 화면의 경로를 나눠 둔다. 묶음별 라우트는 userRoutes.tsx·operatorRoutes.tsx에 있다.

// 사용자(모바일) 화면
export const userPaths = {
  noteList: '/', // F1-1 과목·노트 목록 (F1-1b 로그인·운영자 상태도 같은 경로, 로그인 안내 시트 F1-1c는 그 위에 열린다)
  noteRead: '/notes/:noteId', // F1-2 노트 읽기 (F1-3 용어 바텀시트는 이 화면 위에 열린다)
  quiz: '/quiz', // F3-3a 오늘의 퀴즈
  login: '/login', // F4-1 로그인
  myInfo: '/me', // F4-5 내 정보 (F4-4 계정 메뉴는 헤더에서 열린다)
} as const

// 운영자(PC) 화면. 운영자 셸(MEG-78)이 이 묶음을 감싸 붙이고, 개별 운영자 화면은 이 아래에 경로를 더한다.
export const operatorPaths = {
  home: '/admin', // F5-1a 운영자 노트 목록 (F1-1b의 "운영자 메뉴" 링크가 여기로 온다)
  glossary: '/admin/glossary', // F5-1c 용어 사전 (용어를 고르지 않으면 첫 용어가 열린다)
  glossaryNew: '/admin/glossary/new', // F5-1e 새 용어
  glossaryTerm: '/admin/glossary/:termId', // F5-1c 용어 수정
  reports: '/admin/reports', // F5-2 신고
  accounts: '/admin/accounts', // F4-3a 계정 발급
} as const

// 개발 중에만 쓰는 경로. 제품 화면이 아니다.
export const devPaths = {
  mockup: '/dev/mockup', // MEG-113 전체 목업 검토. 제품 경로와 데이터는 분리한다.
  foundationDemo: '/dev/foundation', // 공통 기반 확인용 샘플 화면(MEG-105)
  componentShowcase: '/dev/components', // 공통 컴포넌트를 한 페이지에 모아 디자인과 비교하는 화면(MEG-70)
} as const

// glossaryTerm 경로에 용어 id를 채운다.
export function glossaryTermPath(termId: number | string): string {
  return operatorPaths.glossaryTerm.replace(':termId', String(termId))
}

// noteRead 경로에 노트 id를 채운다.
export function noteReadPath(noteId: number | string): string {
  return userPaths.noteRead.replace(':noteId', String(noteId))
}
