// 단계별 지도 (MEG-287). 노드 자리는 모든 단계에서 그대로이고, 회색 얇은 실선은 전체 경로,
// 굵은 실선·화살촉·번호 상자는 지금 단계다(MEG-270 결정 1·2·4). 색은 tokens.css만 쓴다.
import type { ReactNode } from 'react'
import { GUIDE_ICON_PATHS } from './icons.ts'
import { guideRoutes, nodeCenter, pairKey, segment, shiftSegment, stepRoles, textWidth, type Segment } from './model.ts'
import type { GuideFile, GuideIcon, GuideNode, GuideStep } from './types.ts'
import styles from './Guide.module.css'

// 기울어진 격자(장식, MEG-270 요소 5). 화면 읽기 프로그램에는 숨긴다.
export function IsoGrid({ w, h, lines = 7 }: { w: number; h: number; lines?: number }) {
  const TL: [number, number] = [w * 0.22, 26]
  const TR: [number, number] = [w - 14, 58]
  const BR: [number, number] = [w * 0.8, h - 22]
  const BL: [number, number] = [16, h - 50]
  const lerp = (p: [number, number], q: [number, number], t: number) => [p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t]
  const out: ReactNode[] = []
  for (let k = 0; k <= lines; k++) {
    const t = k / lines
    const a = lerp(TL, BL, t)
    const b = lerp(TR, BR, t)
    const c = lerp(TL, TR, t)
    const d = lerp(BL, BR, t)
    out.push(<line key={`r${k}`} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} />, <line key={`c${k}`} x1={c[0]} y1={c[1]} x2={d[0]} y2={d[1]} />)
  }
  return (
    <g className={styles.grid} aria-hidden="true">
      {out}
    </g>
  )
}

// 아이콘 받침과 Material 아이콘. (cx, y)는 노드 상자의 가운데 위쪽이다.
export function NodeIcon({ icon, cx, y }: { icon: GuideIcon; cx: number; y: number }) {
  const s = 44 / 960
  return (
    <g aria-hidden="true">
      <polygon className={styles.platform} points={[cx - 42, y + 46, cx + 6, y + 36, cx + 42, y + 46, cx - 6, y + 58].join(' ')} />
      <path className={styles.icon} d={GUIDE_ICON_PATHS[icon].d} transform={`translate(${cx - 22} ${y + 48}) scale(${s})`} />
    </g>
  )
}

function ArrowHead({ x, y, ux, uy }: { x: number; y: number; ux: number; uy: number }) {
  const nx = -uy
  const ny = ux
  const bx = x - ux * 12
  const by = y - uy * 12
  return <polygon className={styles.currentHead} points={[x, y, bx + nx * 6, by + ny * 6, bx - nx * 6, by - ny * 6].join(' ')} />
}

// 사라진 메시지: 선을 중간에서 끊고 끊긴 끝에 X를 둔다(MEG-270 결정 6).
function LostLine({ s }: { s: Segment }) {
  const ex = s.x1 + (s.x2 - s.x1) * 0.55
  const ey = s.y1 + (s.y2 - s.y1) * 0.55
  const mx = ex + s.ux * 12
  const my = ey + s.uy * 12
  return (
    <>
      <line className={styles.currentLine} x1={s.x1} y1={s.y1} x2={ex} y2={ey} />
      <path className={styles.lostMark} d={`M${mx - 7} ${my - 7} L${mx + 7} ${my + 7} M${mx + 7} ${my - 7} L${mx - 7} ${my + 7}`} />
    </>
  )
}

// 움직이는 공과 도착 물결. 1~2회 재생하고 멈춘다(MEG-270 요소 3). 동작 줄이기 설정이면 그리지 않는다.
function Ball({ s, idx, total, dest }: { s: Segment; idx: number; total: number; dest: [number, number] }) {
  const MOVE = 1.6
  const GAP = 0.5
  const T = total * (MOVE + GAP) + 0.7
  const a = ((idx * (MOVE + GAP)) / T).toFixed(4)
  const b = ((idx * (MOVE + GAP) + MOVE) / T).toFixed(4)
  const c = Math.min(1, (idx * (MOVE + GAP) + MOVE + 0.45) / T).toFixed(4)
  const dur = `${T.toFixed(2)}s`
  return (
    <g aria-hidden="true">
      <circle className={styles.ring} cx={dest[0]} cy={dest[1]} r={26} opacity={0}>
        <animate attributeName="r" dur={dur} repeatCount="2" values="26;26;46;46" keyTimes={`0;${b};${c};1`} />
        <animate attributeName="opacity" dur={dur} repeatCount="2" values="0;0;0.7;0;0" keyTimes={`0;${b};${b};${c};1`} />
      </circle>
      <circle className={styles.ball} r={7} opacity={0}>
        <animateMotion dur={dur} repeatCount="2" calcMode="linear" path={`M ${s.x1} ${s.y1} L ${s.x2} ${s.y2}`} keyPoints="0;0;1;1" keyTimes={`0;${a};${b};1`} />
        <animate attributeName="opacity" dur={dur} repeatCount="2" calcMode="discrete" values="0;1;0" keyTimes={`0;${a};${b}`} />
      </circle>
    </g>
  )
}

function Pill({ x, y, text, className, textClassName }: { x: number; y: number; text: string; className: string; textClassName: string }) {
  const w = textWidth(text, 12) + 14
  return (
    <g>
      <rect className={className} x={x - w / 2} y={y - 11} width={w} height={22} rx={11} />
      <text className={textClassName} x={x} y={y + 4.5} textAnchor="middle">
        {text}
      </text>
    </g>
  )
}

export type StepMapProps = {
  guide: GuideFile
  step: GuideStep
  stepNumber: number
  // 좁은 화면이면 모바일 배치(nodes_mobile)를 쓴다. 없으면 PC 배치를 줄여 쓴다.
  narrow: boolean
  reducedMotion: boolean
}

export function StepMap({ guide, step, stepNumber, narrow, reducedMotion }: StepMapProps) {
  const useMobile = narrow && guide.map.nodes_mobile !== undefined && guide.map.view_mobile !== undefined
  const view = useMobile ? guide.map.view_mobile! : guide.map.view
  const nodes = useMobile ? guide.map.nodes_mobile! : guide.map.nodes
  const byId = new Map<string, GuideNode>(nodes.map((n) => [n.id, n]))
  const node = (id: string) => {
    const n = byId.get(id)
    if (!n) throw new Error(`지도에 없는 노드: ${id}`)
    return n
  }
  const routes = guideRoutes(guide)
  const current = new Map<string, typeof step.arrows>()
  step.arrows.forEach((a) => {
    const k = pairKey(a.from, a.to)
    current.set(k, [...(current.get(k) ?? []), a])
  })
  const roles = stepRoles(step)
  const moving = step.arrows.filter((a) => !a.local && a.from !== a.to)

  return (
    <svg className={styles.mapSvg} viewBox={`0 0 ${view[0]} ${view[1]}`} role="img" aria-label={`${stepNumber}단계 지도: ${step.title}`}>
      <IsoGrid w={view[0]} h={view[1]} />
      {/* 회색 얇은 실선: 지금 단계가 아닌 전체 경로와 그 경로를 쓰는 단계 번호 */}
      {[...routes].map(([k, r]) => {
        if (current.has(k) || r.a === r.b) return null
        const s = segment(node(r.a), node(r.b))
        const label = r.steps.join(' · ')
        const w = textWidth(label, 12) + 12
        const mx = (s.x1 + s.x2) / 2
        const my = (s.y1 + s.y2) / 2
        return (
          <g key={`route-${k}`} aria-hidden="true">
            <line className={styles.routeLine} x1={s.x1} y1={s.y1} x2={s.x2} y2={s.y2} />
            <rect className={styles.routeTagBg} x={mx - w / 2} y={my - 11} width={w} height={22} rx={4} />
            <text className={styles.routeTag} x={mx} y={my + 4.5} textAnchor="middle">
              {label}
            </text>
          </g>
        )
      })}
      {/* 진한 실선: 지금 단계 */}
      {[...current].map(([k, list]) => {
        const first = list[0]
        if (first.from === first.to) return null
        const both = list.some((a) => a.from !== first.from)
        const base = shiftSegment(segment(node(first.from), node(first.to)), first.shift)
        const s: Segment = {
          ...base,
          x1: base.x1 + (both ? base.ux * 10 : 0),
          y1: base.y1 + (both ? base.uy * 10 : 0),
          x2: base.x2 - base.ux * 10,
          y2: base.y2 - base.uy * 10,
        }
        const lost = list.every((a) => a.style === 'bad')
        const nx = -base.uy
        const ny = base.ux
        const mx = (base.x1 + base.x2) / 2 + nx * 17
        const my = (base.y1 + base.y2) / 2 + ny * 17
        return (
          <g key={`cur-${k}`} aria-hidden="true">
            {lost ? (
              <LostLine s={s} />
            ) : (
              <>
                <line className={styles.currentLine} x1={s.x1} y1={s.y1} x2={s.x2} y2={s.y2} />
                <ArrowHead x={base.x2} y={base.y2} ux={base.ux} uy={base.uy} />
                {both && <ArrowHead x={base.x1} y={base.y1} ux={-base.ux} uy={-base.uy} />}
              </>
            )}
            <rect className={styles.currentBadge} x={mx - 12} y={my - 12} width={24} height={24} rx={4} />
            <text className={styles.currentNum} x={mx} y={my + 5} textAnchor="middle">
              {stepNumber}
            </text>
          </g>
        )
      })}
      {!reducedMotion &&
        moving.map((a, idx) => {
          const s = segment(node(a.from), node(a.to))
          return <Ball key={`ball-${idx}`} s={s} idx={idx} total={moving.length} dest={nodeCenter(node(a.to))} />
        })}
      {nodes.map((n) => {
        const on = step.active.includes(n.id)
        const cx = n.x + 60
        const note = step.notes[n.id]
        return (
          <g key={n.id} className={on ? undefined : styles.nodeOff}>
            <NodeIcon icon={n.icon} cx={cx} y={n.y} />
            {roles[n.id] && <Pill x={cx} y={n.y - 14} text={roles[n.id]} className={styles.rolePill} textClassName={styles.roleText} />}
            <text className={styles.nodeLabel} x={cx} y={n.y + 76} textAnchor="middle">
              {n.label}
            </text>
            <text className={styles.nodeSub} x={cx} y={n.y + 92} textAnchor="middle">
              {n.sub}
            </text>
            {note && (
              <text className={styles.nodeNote} x={cx} y={n.y + 110} textAnchor="middle">
                {note}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}
