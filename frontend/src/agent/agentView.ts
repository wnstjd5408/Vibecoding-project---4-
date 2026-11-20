// CS Agent 패널의 보기 방식(MEG-261, T6f). PC에서만 쓴다. 모바일은 늘 전체 높이 대화 화면이다(결정 25).
//  - panel: 오른쪽 480px 패널(기본, F6-3)
//  - floating: 오른쪽 아래의 떠 있는 창(F6-3f)
//  - fullscreen: 대화만 가운데 읽기 폭으로 보는 전체 화면(F6-3x, 결정 42~44)
// 마지막으로 쓴 보기 방식은 브라우저 저장소에 남긴다(14.5 AI 제안). 저장소가 막혀 있으면 이 탭에서만 기억한다.
import { useCallback, useState } from 'react'

export type AgentView = 'panel' | 'floating' | 'fullscreen'

export const AGENT_VIEW_STORAGE_KEY = 'cs-agent.view'

const VIEWS: readonly AgentView[] = ['panel', 'floating', 'fullscreen']
const isView = (value: unknown): value is AgentView => VIEWS.includes(value as AgentView)

// 저장소를 쓸 수 없을 때(사생활 보호 모드, 막힌 사이트 데이터 등)의 대신 기억. 노트를 옮겨 다녀도 이 탭 안에서는 남는다.
let remembered: AgentView | null = null

export function readAgentView(): AgentView {
  try {
    const stored = window.localStorage.getItem(AGENT_VIEW_STORAGE_KEY)
    if (isView(stored)) return stored
  } catch {
    // 저장소를 읽지 못해도 화면은 기본 보기로 연다.
  }
  return remembered ?? 'panel'
}

function storeAgentView(view: AgentView) {
  remembered = view
  try {
    window.localStorage.setItem(AGENT_VIEW_STORAGE_KEY, view)
  } catch {
    // 저장하지 못해도 보기 전환은 그대로 된다.
  }
}

// 실제로 그릴 보기. 모바일이면 늘 전체 높이 화면이다(여기서는 panel로 돌려주고 AgentPanel이 wide로 가른다).
// 전체 화면에서 출처를 열면 출처 보기(F6-4, 노트 자리에 인용 문단)를 쓰려고 잠시 패널로 그린다. 고른 보기는 바뀌지 않아 돌아오면 다시 전체 화면이다.
export function shownAgentView(view: AgentView, wide: boolean, sourceOpen: boolean): AgentView {
  if (!wide) return 'panel'
  if (view === 'fullscreen' && sourceOpen) return 'panel'
  return view
}

// 노트 화면이 가지는 보기 방식. 패널을 닫았다 열어도, 다른 노트로 가도 마지막 보기 방식으로 연다.
export function useAgentView(): [AgentView, (view: AgentView) => void] {
  const [view, setView] = useState<AgentView>(readAgentView)
  const change = useCallback((next: AgentView) => {
    storeAgentView(next)
    setView(next)
  }, [])
  return [view, change]
}
