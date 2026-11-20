// 노트 화면의 CS Agent 대화 상태 훅(MEG-255).
// 대화는 같은 노트 화면에 있는 동안만 메모리에 둔다(MEG-239 결정 요청 10 권장안 잠정 적용).
//  - 노트 화면(NoteReadPage)에서 부른다. 패널 안에서 부르면 패널을 닫을 때 대화가 사라진다.
//  - 다른 노트로 가거나 로그인 세션이 바뀌면 새 대화 상태로 바꾼다. 새로 고치면 복원하지 않는다.
//  - 화면을 떠나면 진행 중인 읽기만 멈춘다. 서버의 턴 실행은 끝까지 간다.
//  - 로그인 세션 번호는 렌더할 때 읽는다. 로그인·로그아웃 뒤 이 훅을 부르는 화면이 다시 렌더돼야 바뀐다(인증 상태를 쓰는 노트 화면은 다시 렌더된다).
//  - 마운트 effect 안에서 ask()를 부르지 않는다. 개발 모드(StrictMode)의 가짜 언마운트가 abort()를 불러 두 번째 E29가 나간다.
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
