import { useSyncExternalStore } from 'react'

// PC 배치 기준 폭. 1024px 이상이면 PC 배치(오른쪽 사이드 패널 등), 미만이면 기존 모바일 배치와 바텀시트다.
// CSS 미디어 쿼리(@media (min-width: 1024px))와 같은 값이어야 하므로 이 한 곳에서만 정한다.
export const WIDE_QUERY = '(min-width: 1024px)'

function subscribe(callback: () => void) {
  const query = window.matchMedia(WIDE_QUERY)
  query.addEventListener('change', callback)
  return () => query.removeEventListener('change', callback)
}

// 지금 화면이 PC 폭인지 알려 준다. 창 크기를 바꾸면 바로 다시 그려진다.
export function useWideLayout(): boolean {
  return useSyncExternalStore(subscribe, () => window.matchMedia(WIDE_QUERY).matches, () => false)
}
