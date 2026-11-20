// CS Agent 'AI에게 질문' 입구를 열지 정한다(MEG-259, T6e). MEG-239 결정 기록 1·2(2026-11-19)를 따른다.
//  1. 노출 중단 플래그가 켜지면 노트 선택 버튼은 기존 'AI 설명'(E09)이고, 꺼지면 'AI에게 질문'이다. 두 버튼을 함께 보이지 않는다.
//  2. 화면은 프론트 빌드 환경변수 VITE_CS_AGENT_DISABLED로 플래그를 안다. 백엔드 CS_AGENT_DISABLED와 환경마다 같은 값으로 둔다.
//     E27·E29가 503 service_unavailable을 돌려줘도 같은 처리로 입구를 닫는다(두 값이 어긋난 배포, 백엔드만 먼저 끈 경우).
// 503으로 닫은 입구는 이 탭을 새로 고칠 때까지 닫혀 있다. 다른 노트로 가도 다시 열지 않는다.
import { useSyncExternalStore } from 'react'

// 값 규칙은 백엔드(backend/app/agent.py agent_disabled)와 같다. 비우거나 0·false·no·off(대소문자·앞뒤 공백 무시)면 꺼짐이고,
// 그 밖의 값은 모두 켜짐이다(잘못 쓴 값도 막는 쪽).
const OFF_VALUES: ReadonlySet<string> = new Set(['', '0', 'false', 'no', 'off'])

export function isDisabledValue(value: unknown): boolean {
  return !OFF_VALUES.has(String(value ?? '').trim().toLowerCase())
}

// Vite가 빌드할 때 값을 박아 넣는다. 바꾸려면 새로 빌드(배포)해야 한다.
export const AGENT_DISABLED_BY_BUILD: boolean = isDisabledValue(import.meta.env.VITE_CS_AGENT_DISABLED)

let closedByServer = false
const listeners = new Set<() => void>()

// E27·E29가 503을 돌려줬다. 새 질문 입구를 닫는다. 이미 열린 대화는 계속 읽을 수 있다(E28·E30·E32는 플래그와 무관하다).
export function closeAgentEntry(): void {
  if (closedByServer) return
  closedByServer = true
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

const snapshot = () => AGENT_DISABLED_BY_BUILD || closedByServer

// 새 질문 입구가 닫혔는가(빌드 플래그 또는 503).
export function useAgentEntryClosed(): boolean {
  return useSyncExternalStore(subscribe, snapshot, snapshot)
}
