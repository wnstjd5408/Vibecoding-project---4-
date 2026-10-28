// 화면이 부르는 API의 응답을 어디서 받을지 고른다. 화면 코드는 같은 apiFetch를 쓰고 이 값만 바뀐다.
//  - real: 개발 서버 프록시를 거친 실제 백엔드(/api)
//  - mock: mocks/handlers.ts의 가짜 응답. 백엔드가 아직 없는 엔드포인트를 쓰는 화면을 먼저 만들 때 쓴다
export type ApiSource = 'real' | 'mock'

// 기본값은 환경변수 VITE_API_MOCK=true일 때만 mock이다.
let current: ApiSource = import.meta.env.VITE_API_MOCK === 'true' ? 'mock' : 'real'

export function getApiSource(): ApiSource {
  return current
}

export function setApiSource(source: ApiSource): void {
  current = source
}
