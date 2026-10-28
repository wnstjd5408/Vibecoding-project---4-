// 요청이 여러 번 겹칠 때 가장 나중에 시작한 요청의 결과만 반영하게 하는 순서표다.
// 늦게 도착한 오래된 응답이 최신 상태를 덮어쓰지 않게 한다(예: 로그아웃 뒤 visitor가 반영됐는데 앞서 보낸 operator 응답이 늦게 오는 경우).
export type LatestRequest = {
  // 새 요청을 시작하고 그 요청의 번호를 돌려준다. 이전 요청들은 이 순간부터 오래된 것이 된다.
  begin: () => number
  // 이 번호가 아직 가장 최근 요청이면 true다.
  isLatest: (id: number) => boolean
}

export function createLatestRequest(): LatestRequest {
  let current = 0
  return {
    begin: () => {
      current += 1
      return current
    },
    isLatest: (id) => id === current,
  }
}
