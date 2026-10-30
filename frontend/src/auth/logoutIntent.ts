// 사용자가 직접 로그아웃한 것(명시적 로그아웃)과 세션 만료·권한 회수(인증 상실)를 구분하는 표시다.
// 둘 다 결과는 "역할이 방문자로 바뀜"이라 상태만으로는 구분할 수 없어, 로그아웃 메뉴가 확인된 로그아웃 직전에 표시한다.
// 운영자 경로 보호(RequireOperator)가 이 표시로 안내 팝업을 띄울지 정한다. 화면 이동과 겹쳐 읽히므로 읽어도 지워지지 않고, 운영자로 다시 들어오면 지운다.
let explicitLogout = false

export function markExplicitLogout(): void {
  explicitLogout = true
}

export function clearExplicitLogout(): void {
  explicitLogout = false
}

export function isExplicitLogout(): boolean {
  return explicitLogout
}
