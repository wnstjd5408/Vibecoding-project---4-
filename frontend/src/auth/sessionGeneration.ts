// 로그인(E01)·로그아웃(E02)이 일어날 때마다 올라가는 세션 번호.
// 표시 이름과 역할이 같은 다른 계정도 서로 다른 번호를 갖는다(표시 이름은 고유하지 않다). 계정마다 따로 두어야 하는 요청·대기 상태가 이 번호로 나뉜다.
let generation = 0

export function currentSession(): number {
  return generation
}

export function startNewSession(): void {
  generation += 1
}
