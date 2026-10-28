// 가짜 응답이 흉내 내는 로그인 상태. E03·E06·E07·E08 응답이 이 값에 따라 달라진다.
export type MockSession = 'visitor' | 'user' | 'operator'

let current: MockSession = 'visitor'

export function getMockSession(): MockSession {
  return current
}

export function setMockSession(session: MockSession): void {
  current = session
}
