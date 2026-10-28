// 화면 경로. 이름 옆 번호는 목업 v0.2의 화면 ID다. 화면 티켓은 여기 경로를 그대로 쓴다.
export const paths = {
  noteList: '/', // F1-1 과목·노트 목록 (F1-1b 로그인·운영자 상태도 같은 경로, 로그인 안내 시트 F1-1c는 그 위에 열린다)
  noteRead: '/notes/:noteId', // F1-2 노트 읽기 (F1-3 용어 바텀시트는 이 화면 위에 열린다)
  quiz: '/quiz', // F3-3a 오늘의 퀴즈
  login: '/login', // F4-1 로그인
  myInfo: '/me', // F4-5 내 정보 (F4-4 계정 메뉴는 헤더에서 열린다)
  foundationDemo: '/dev/foundation', // 공통 기반 확인용 샘플 화면(MEG-105). 제품 화면이 아니다
} as const

// noteRead 경로에 노트 id를 채운다.
export function noteReadPath(noteId: number | string): string {
  return paths.noteRead.replace(':noteId', String(noteId))
}
