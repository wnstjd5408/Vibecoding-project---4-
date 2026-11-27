// 가이드 파일에서 화면에 필요한 값을 계산하는 순수 함수 (MEG-287).
// 그리기와 글이 같은 계산을 쓰게 해서, 지도를 못 그려도 글로 같은 내용을 읽을 수 있게 한다(PRD AC-5).
import type { GuideArrow, GuideFile, GuideNode, GuideStep } from './types.ts'

// 화면에서 넘기는 한 칸. 보통은 단계이고, 전체 흐름을 부록으로 두면 마지막에 부록 칸이 하나 더 붙는다.
export type GuideView =
  | { kind: 'step'; index: number; step: GuideStep }
  | { kind: 'appendix'; index: number }

export function guideViews(guide: GuideFile): GuideView[] {
  const views: GuideView[] = guide.steps.map((step, index) => ({ kind: 'step', index, step }))
  if (guide.sequence?.placement === 'appendix' && guide.sequence.appendix) views.push({ kind: 'appendix', index: guide.steps.length })
  return views
}

// 이 칸에서 지도 대신 전체 흐름(시퀀스)을 보여 주는지.
export function showsSequence(guide: GuideFile, view: GuideView): boolean {
  if (!guide.sequence) return false
  if (view.kind === 'appendix') return true
  return guide.sequence.placement === 'last_step' && view.index === guide.steps.length - 1
}

export const pairKey = (a: string, b: string) => [a, b].sort().join('|')

// 지도에 그릴 메시지 하나. 화살표마다 따로 그리고, 같은 노드 쌍을 오가는 메시지는 곡선의 휘는 정도(차선)를 달리해 겹치지 않게 한다.
export type MapArrow = { stepIndex: number; arrowIndex: number; arrow: GuideArrow; p0: [number, number]; c: [number, number]; p1: [number, number] }
export function mapArrows(guide: GuideFile, nodes: GuideNode[]): MapArrow[] {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const items: { stepIndex: number; arrowIndex: number; arrow: GuideArrow }[] = []
  guide.steps.forEach((s, si) => s.arrows.forEach((a, ai) => {
    if (a.from !== a.to && byId.has(a.from) && byId.has(a.to)) items.push({ stepIndex: si, arrowIndex: ai, arrow: a })
  }))
  const lanes = new Map<string, number>()
  const counts = new Map<string, number>()
  items.forEach((it) => counts.set(pairKey(it.arrow.from, it.arrow.to), (counts.get(pairKey(it.arrow.from, it.arrow.to)) ?? 0) + 1))
  const out: MapArrow[] = []
  for (const it of items) {
    const key = pairKey(it.arrow.from, it.arrow.to)
    const lane = lanes.get(key) ?? 0
    lanes.set(key, lane + 1)
    const count = counts.get(key) ?? 1
    const from = byId.get(it.arrow.from) as GuideNode
    const to = byId.get(it.arrow.to) as GuideNode
    const s = segment(from, to)
    if (Math.hypot(s.x2 - s.x1, s.y2 - s.y1) < 1) continue
    // 휘는 방향은 노드 쌍의 정해진 순서(id 사전순)를 기준으로 잡아, 반대 방향 메시지도 같은 차선 규칙을 따른다.
    const [a, b] = [it.arrow.from, it.arrow.to].sort()
    const ca = nodeCenter(byId.get(a) as GuideNode)
    const cb = nodeCenter(byId.get(b) as GuideNode)
    const len = Math.hypot(cb[0] - ca[0], cb[1] - ca[1]) || 1
    const nx = -(cb[1] - ca[1]) / len
    const ny = (cb[0] - ca[0]) / len
    const spacing = Math.min(28, 150 / count)
    const offset = (lane - (count - 1) / 2) * spacing
    const mx = (s.x1 + s.x2) / 2 + nx * offset * 2
    const my = (s.y1 + s.y2) / 2 + ny * offset * 2
    out.push({ ...it, p0: [s.x1, s.y1], c: [mx, my], p1: [s.x2, s.y2] })
  }
  return out
}

// 노드 위 역할 표시. 파일에 roles가 있으면 그대로 쓰고, 없으면 화살표 방향으로 정한다.
// 질문과 답이 오가면 묻는 쪽·답하는 쪽, 한 방향이면 출발·도착이다(K-2의 역할 6종).
// 「보내는 쪽·확인하는 쪽」처럼 질문이 아닌 왕복은 화살표로 알 수 없으므로 가이드 파일의 roles에 적는다.
export function stepRoles(step: GuideStep): Record<string, string> {
  if (step.roles) return step.roles
  const r: Record<string, string> = {}
  const moving = step.arrows.filter((a) => !a.local)
  if (moving.length === 0) return r
  const start = moving[0].from
  const asks = moving.some((a) => a.to === start)
  if (!asks) {
    moving.forEach((a) => {
      r[a.from] = r[a.from] ?? '출발'
      r[a.to] = '도착'
    })
    return r
  }
  r[start] = '묻는 쪽'
  moving.forEach((a) => {
    if (a.from !== start) r[a.from] = '답하는 쪽'
  })
  moving.forEach((a) => {
    if (a.from === start && !moving.some((b) => b.from === a.to)) r[a.to] = '도착'
  })
  return r
}

const ORDER_MARK = /^[①②③④⑤⑥⑦⑧⑨] /
// 메시지 이름 앞의 순서 표시(①②…). 없으면 null.
export const orderMark = (label: string): string | null => (ORDER_MARK.test(label) ? label[0] : null)
// 「①②는 …」처럼 순서 표시 뒤의 조사. 일·삼·육·칠·팔은 받침이 있어 「은」이다.
export function orderNote(step: GuideStep): string | null {
  const marks = step.arrows.map((a) => orderMark(a.label)).filter((x): x is string => x !== null)
  if (marks.length === 0) return null
  const lastMark = marks[marks.length - 1]
  const josa = '①③⑥⑦⑧'.includes(lastMark) ? '은' : '는'
  return `${marks.join('')}${josa} 이 단계 안에서 일어나는 순서예요.`
}

// 따라가기 상자: 누가 누구에게(경로)와 무엇을(메시지). 지도 없이도 읽히는 글이다(PRD AC-5).
export type FollowCallout = { route: string; message: string; ordered: boolean }
export function followCallout(guide: GuideFile, step: GuideStep): FollowCallout {
  const label = (id: string) => guide.map.nodes.find((n) => n.id === id)?.label ?? id
  const arrows = step.arrows
  if (arrows.length > 0 && arrows.every((a) => a.local)) {
    return { route: `${label(arrows[0].from)} 안에서 확인해요`, message: arrows.map((a) => a.label).join('  /  '), ordered: false }
  }
  const seen: string[] = []
  const parts: string[] = []
  arrows.forEach((a) => {
    const k = pairKey(a.from, a.to)
    if (seen.includes(k)) return
    seen.push(k)
    const both = arrows.some((b) => pairKey(b.from, b.to) === k && b.from !== a.from)
    parts.push(`${label(a.from)}${both ? ' ↔ ' : ' → '}${label(a.to)}`)
  })
  // 메시지가 없는 단계: 같은 표시는 한 번만 적고 누구의 표시인지 이름을 붙인다.
  const grouped = new Map<string, string[]>()
  Object.entries(step.notes).forEach(([id, t]) => grouped.set(t, [...(grouped.get(t) ?? []), label(id)]))
  const noteLine = [...grouped].map(([t, who]) => `${who.join('·')}: ${t}`).join('  /  ')
  // 경로가 둘 이상이면 메시지마다 경로를 붙여 어느 쪽 메시지인지 알 수 있게 한다.
  const messages = arrows.map((a) =>
    seen.length > 1 ? a.label.replace(ORDER_MARK, (m) => `${m}${label(a.from)} → ${label(a.to)}: `) : a.label,
  )
  return {
    route: parts.length > 0 ? parts.join(', ') : '이 단계에는 오가는 메시지가 없어요',
    message: arrows.length > 0 ? messages.join('  /  ') : noteLine,
    ordered: arrows.some((a) => ORDER_MARK.test(a.label)),
  }
}

// 전체 흐름을 글 목록으로 만든다. 그림 판과 같은 내용이다.
export function sequenceLines(guide: GuideFile): string[] {
  const seq = guide.sequence
  if (!seq) return []
  const who = Object.fromEntries(seq.actors.map((a) => [a.id, a.name]))
  return seq.rows.map((r) =>
    r.k === 'msg'
      ? `${r.step}단계 · ${who[r.from]} → ${who[r.to]}: ${r.label} (${seq.tags[r.prot]})`
      : `${r.step}단계 · ${r.at === 'both' ? seq.actors.map((a) => a.name).join('·') : who[r.at]}: ${r.label}`,
  )
}

// 지도 좌표 계산. 노드 상자는 120×96이고 아이콘 중심은 위에서 24px 아래다(내용 초안 생성기와 같은 값).
export const NODE_W = 120
export const NODE_H = 96
export const nodeCenter = (n: GuideNode): [number, number] => [n.x + NODE_W / 2, n.y + 24]

function exitPoint(n: GuideNode, tx: number, ty: number): [number, number] {
  const [cx, cy] = nodeCenter(n)
  const dx = tx - cx
  const dy = ty - cy
  let t = Infinity
  if (dx > 0) t = Math.min(t, 46 / dx)
  if (dx < 0) t = Math.min(t, -46 / dx)
  if (dy > 0) t = Math.min(t, (n.y + NODE_H + 5 - cy) / dy)
  if (dy < 0) t = Math.min(t, (n.y - 22 - cy) / dy)
  if (!Number.isFinite(t)) t = 0
  return [cx + dx * t, cy + dy * t]
}

export type Segment = { x1: number; y1: number; x2: number; y2: number; ux: number; uy: number }
export function segment(from: GuideNode, to: GuideNode): Segment {
  const ac = nodeCenter(from)
  const bc = nodeCenter(to)
  const [x1, y1] = exitPoint(from, bc[0], bc[1])
  const [x2, y2] = exitPoint(to, ac[0], ac[1])
  const len = Math.hypot(x2 - x1, y2 - y1) || 1
  return { x1, y1, x2, y2, ux: (x2 - x1) / len, uy: (y2 - y1) / len }
}

// 글자 폭 어림값(한글은 글자 크기만큼, 영문은 0.56배). 이름표 바탕 상자 너비에 쓴다.
export function textWidth(s: string, px: number): number {
  let w = 0
  for (const ch of s) w += ch.charCodeAt(0) > 0x2e80 ? px : px * 0.56
  return w
}
