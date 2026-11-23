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

// 위키 플래그(MEG-254 결정 2, 2026-11-23). 화면은 빌드 환경변수 VITE_CS_AGENT_WIKI_ENABLED로 안다. 백엔드 CS_AGENT_WIKI_ENABLED(MEG-252)와
// 환경마다 같은 값으로 둔다. 켜는 것은 T4d(MEG-253)에서 사람이 정한다.
// 값 규칙은 백엔드(backend/app/agent_retrieval.py wiki_enabled)와 같다. 1·true·yes·on(대소문자·앞뒤 공백 무시)만 켜짐이고, 그 밖은 모두 꺼짐이다.
const ON_VALUES: ReadonlySet<string> = new Set(['1', 'true', 'yes', 'on'])

export function isWikiOnValue(value: unknown): boolean {
  return ON_VALUES.has(String(value ?? '').trim().toLowerCase())
}

export const WIKI_ENABLED_BY_BUILD: boolean = isWikiOnValue(import.meta.env.VITE_CS_AGENT_WIKI_ENABLED)

// 두 값이 어긋난 배포에서 E27 origin wiki가 422(플래그 꺼짐)나 503을 돌려주면 위키 질문 입구를 닫는다. 이 탭을 새로 고칠 때까지 닫혀 있다.
let wikiClosedByServer = false
const wikiListeners = new Set<() => void>()

export function closeWikiEntry(): void {
  if (wikiClosedByServer) return
  wikiClosedByServer = true
  for (const listener of wikiListeners) listener()
}

function subscribeWiki(listener: () => void): () => void {
  wikiListeners.add(listener)
  return () => wikiListeners.delete(listener)
}

const wikiSnapshot = () => WIKI_ENABLED_BY_BUILD && !wikiClosedByServer

// 위키 질문 입구('위키 출처 → 용어 시트'의 'AI에게 질문')가 열려 있는가. 노출 중단(useAgentEntryClosed)은 따로 본다.
export function useWikiEntryOpen(): boolean {
  return useSyncExternalStore(subscribeWiki, wikiSnapshot, wikiSnapshot)
}

// 위키 출처의 source_id(`glossary:{term_id}`, MEG-163 W7)를 term_id로 바꾼다. 위키 출처가 아니거나 모양이 틀리면 null이다(백엔드 parse_wiki_ref와 같은 규칙).
export function wikiTermId(sourceId: string | undefined | null): number | null {
  const match = /^glossary:([1-9][0-9]*)$/.exec(sourceId ?? '')
  if (!match) return null
  const id = Number(match[1])
  return Number.isSafeInteger(id) ? id : null
}

export const wikiRef = (termId: number) => `glossary:${termId}`
