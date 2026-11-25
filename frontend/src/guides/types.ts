// 단계별 지도 가이드 한 편의 파일 형식 (PRD v0.5 5.3절, MEG-286).
// 파일 하나 = 한 편 한 판. 위치는 src/guides/content/<slug>.json 이고,
// 공개한 가이드만 src/guides/content/index.json 에 올린다.

export const GUIDE_SCHEMA_VERSION = 1

// 지도 노드에 쓰는 아이콘 이름. 실제 모양은 Material Symbols Outlined(Apache 2.0)다(MEG-291).
export const GUIDE_ICONS = [
  'client', 'server', 'user', 'cert', 'check', 'store', 'cache', 'link', 'auth', 'api', 'key',
] as const
export type GuideIcon = (typeof GUIDE_ICONS)[number]

// 단계 구분 표시(문제 → 과정 → 해결 …).
export const GUIDE_STEP_KINDS = ['문제', '과정', '해결', '정리', '확인'] as const
export type GuideStepKind = (typeof GUIDE_STEP_KINDS)[number]

export const GUIDE_ARROW_STYLES = ['ok', 'bad'] as const
export type GuideArrowStyle = (typeof GUIDE_ARROW_STYLES)[number]

export const GUIDE_SEQUENCE_PLACEMENTS = ['last_step', 'appendix'] as const
export type GuideSequencePlacement = (typeof GUIDE_SEQUENCE_PLACEMENTS)[number]

export type GuideNode = {
  id: string
  x: number
  y: number
  icon: GuideIcon
  label: string
  sub: string
}

export type GuideMap = {
  view: [number, number]
  nodes: GuideNode[]
  // 좁은 화면용 배치(MEG-270 결정 5). 둘 다 있거나 둘 다 없어야 한다.
  // 없으면 화면이 PC 배치를 줄여 쓴다. 노드 id 집합은 nodes와 같아야 한다.
  view_mobile?: [number, number]
  nodes_mobile?: GuideNode[]
}

export type GuideArrow = {
  from: string
  to: string
  label: string
  // 네트워크를 건너지 않는 확인(예: 브라우저가 자기 신뢰 저장소로 인증서를 확인). 공을 움직이지 않는다.
  // from과 to가 달라도 된다(브라우저 → 신뢰 저장소).
  local?: boolean
  // 결과 표시: 성공(ok)과 실패(bad).
  style?: GuideArrowStyle
  // 같은 두 노드 사이의 화살표를 겹치지 않게 띄우는 거리(px).
  shift?: number
}

export type GuideAside = { title: string; body: string }

export type GuideStep = {
  short: string
  kind: GuideStepKind
  title: string
  body: string[]
  changed: string[]
  active: string[]
  arrows: GuideArrow[]
  // 노드 아래에 붙는 짧은 상태 표시. 키는 노드 id.
  notes: Record<string, string>
  // 노드 위 역할 표시(출발, 도착, 묻는 쪽 …). 없으면 화살표에서 정한다.
  roles?: Record<string, string>
  aside?: GuideAside
  // figures의 이름.
  figure?: string
}

export type GuideFigureNode = GuideNode & { off?: boolean }

export type GuideFigureEdge = {
  from: string
  to: string
  label?: string
  faint?: boolean
  lx?: number
  ly?: number
  oy?: number
}

export type GuideFigurePanel = {
  title: string
  view: [number, number]
  desc: string
  nodes: GuideFigureNode[]
  edges: GuideFigureEdge[]
  notes: { x: number; y: number; text: string }[]
}

export type GuideSequenceActor = { id: string; name: string }

export type GuideSequenceMessage = { k: 'msg'; step: number; from: string; to: string; label: string; prot: string }
// at은 참여자 id 또는 'both'(양쪽에 걸친 표시).
export type GuideSequenceNote = { k: 'note'; step: number; at: string; label: string }
export type GuideSequenceRow = GuideSequenceMessage | GuideSequenceNote

export type GuideAppendix = {
  short: string
  title: string
  body: string[]
  callout: { route: string; msg: string }
}

export type GuideSequence = {
  // 전체 흐름을 마지막 단계에 둘지, 마지막 단계 뒤 부록 칸에 둘지(PRD v0.5 5.6절 4번).
  placement: GuideSequencePlacement
  actors: GuideSequenceActor[]
  // 선 모양 이름(prot) → 화면에 쓰는 설명.
  tags: Record<string, string>
  legend: [string, string][]
  note?: string
  rows: GuideSequenceRow[]
  // placement가 'appendix'일 때만 쓴다.
  appendix?: GuideAppendix
}

// 사람의 기술 검수 기록(PRD v0.5 AC-7). 공개하는 판에는 반드시 있어야 한다.
export type GuideReview = {
  reviewer: string
  reviewed_on: string // YYYY-MM-DD
  sources: string[]
  record_url: string // 검수 기록이 있는 Linear 이슈 주소(https)
}

export type GuideFile = {
  schema_version: typeof GUIDE_SCHEMA_VERSION
  slug: string
  title: string
  scene: string
  note: string
  term_key: string | null // 가이드가 가리키는 사전 용어(PRD 3.2절 1번 ①)
  note_id: string | null // 가이드 연결을 그릴 노트
  revision: number
  review: GuideReview | null
  end_text?: string
  map: GuideMap
  steps: GuideStep[]
  figures: Record<string, GuideFigurePanel[]>
  sequence?: GuideSequence
}

// src/guides/content/index.json의 한 줄. 공개한 가이드만 올린다.
export type GuideIndexEntry = {
  slug: string
  title: string
  note_id: string
  term_key: string
}
