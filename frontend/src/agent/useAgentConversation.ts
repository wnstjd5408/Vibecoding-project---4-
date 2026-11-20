// 노트 화면의 CS Agent 대화 상태 훅(MEG-255).
// 대화는 같은 노트 화면에 있는 동안만 메모리에 둔다(MEG-239 결정 요청 10 권장안 잠정 적용).
//  - 노트 화면(NoteReadPage)에서 부른다. 패널 안에서 부르면 패널을 닫을 때 대화가 사라진다.
//  - 다른 노트로 가거나 로그인 세션이 바뀌면 새 대화 상태로 바꾼다. 새로 고치면 복원하지 않는다.
//  - 화면을 떠나면 진행 중인 읽기만 멈춘다. 서버의 턴 실행은 끝까지 간다.
import { useEffect, useState, useSyncExternalStore } from 'react'
import { currentSession } from '../auth/sessionGeneration.ts'
import { AgentConversationController } from './conversation.ts'
import type { AgentState } from './conversation.ts'

export function useAgentConversation(noteId: number): { state: AgentState; controller: AgentConversationController } {
  const key = `${currentSession()}:${noteId}`
  const [holder, setHolder] = useState(() => ({ key, controller: new AgentConversationController() }))
  let current = holder
  if (holder.key !== key) {
    // 렌더 중에 파생 상태를 바꾸는 React 권장 방식이다. 이전 대화는 아래 effect 정리에서 멈춘다.
    current = { key, controller: new AgentConversationController() }
    setHolder(current)
  }
  const { controller } = current
  useEffect(() => () => controller.abort(), [controller])
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot)
  return { state, controller }
}
