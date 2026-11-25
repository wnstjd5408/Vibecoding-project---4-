import { useSyncExternalStore } from 'react'

const REDUCED_QUERY = '(prefers-reduced-motion: reduce)'
function subscribeReduced(callback: () => void) {
  const q = window.matchMedia(REDUCED_QUERY)
  q.addEventListener('change', callback)
  return () => q.removeEventListener('change', callback)
}
// 기기의 움직임 줄이기 설정(PRD AC-3). 켜져 있으면 공과 물결을 그리지 않는다.
export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribeReduced, () => window.matchMedia(REDUCED_QUERY).matches, () => false)
}
