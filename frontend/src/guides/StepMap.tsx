// 단계별 지도 (MEG-287). 노드 자리는 모든 단계에서 그대로다.
// - 다른 단계의 메시지: 회색 얇은 실선 곡선과 그 단계 번호(MEG-270 결정 2)
// - 지금 단계의 메시지: 화살표마다 굵은 실선 곡선·화살촉·번호 상자(①② 순서가 있으면 그 번호, 결정 4)
// - lost(사라짐): 곡선을 중간에서 끊고 X(결정 6), risk(도착하지만 위험): 「위험」 표시
// 색은 tokens.css만 쓴다. 지도 너비가 640보다 크면 글자를 그만큼 키워 600px 칸에서도 줄지 않게 한다(결정 7).
import type { CSSProperties, ReactNode } from 'react'
import { GUIDE_ICON_PATHS } from './icons.ts'
import { mapArrows, orderMark, stepRoles, textWidth, type MapArrow } from './model.ts'
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

type P = [number, number]
const at = (m: MapArrow, t: number): P => {
  const u = 1 - t
  return [u * u * m.p0[0] + 2 * u * t * m.c[0] + t * t * m.p1[0], u * u * m.p0[1] + 2 * u * t * m.c[1] + t * t * m.p1[1]]
}
const tangent = (m: MapArrow, t: number): P => {
  const dx = 2 * (1 - t) * (m.c[0] - m.p0[0]) + 2 * t * (m.p1[0] - m.c[0])
  const dy = 2 * (1 - t) * (m.c[1] - m.p0[1]) + 2 * t * (m.p1[1] - m.c[1])
  const len = Math.hypot(dx, dy) || 1
  return [dx / len, dy / len]
}
const curvePath = (m: MapArrow) => `M ${m.p0[0]} ${m.p0[1]} Q ${m.c[0]} ${m.c[1]} ${m.p1[0]} ${m.p1[1]}`
// 곡선의 앞 t만큼만 그리는 경로(드 카스텔조 분할).
const partialPath = (m: MapArrow, t: number) => {
  const q: P = [m.p0[0] + (m.c[0] - m.p0[0]) * t, m.p0[1] + (m.c[1] - m.p0[1]) * t]
  const r = at(m, t)
  return { d: `M ${m.p0[0]} ${m.p0[1]} Q ${q[0]} ${q[1]} ${r[0]} ${r[1]}`, end: r }
}

function ArrowHead({ tip, dir }: { tip: P; dir: P }) {
  const [ux, uy] = dir
  const nx = -uy
  const ny = ux
  const bx = tip[0] - ux * 12
  const by = tip[1] - uy * 12
  return <polygon className={styles.currentHead} points={[tip[0], tip[1], bx + nx * 6, by + ny * 6, bx - nx * 6, by - ny * 6].join(' ')} />
}

function Badge({ at: p, text, current }: { at: P; text: string; current: boolean }) {
  const w = Math.max(current ? 24 : 20, textWidth(text, 13) + 10)
  const h = current ? 24 : 20
  return (
    <g>
      <rect className={current ? styles.currentBadge : styles.routeTagBg} x={p[0] - w / 2} y={p[1] - h / 2} width={w} height={h} rx={4} />
      <text className={current ? styles.currentNum : styles.routeTag} x={p[0]} y={p[1] + 4.5} textAnchor="middle">
        {text}
      </text>
    </g>
  )
}

// 공과 도착 물결. 두 번 재생하고 멈춘다(MEG-270 요소 3). 사라지는 메시지는 끊긴 곳까지만 가고 물결이 없다.
function Ball({ path, idx, total, dest }: { path: string; idx: number; total: number; dest: P | null }) {
  const MOVE = 1.6
  const GAP = 0.5
  const T = total * (MOVE + GAP) + 0.7
  const a = ((idx * (MOVE + GAP)) / T).toFixed(4)
  const b = ((idx * (MOVE + GAP) + MOVE) / T).toFixed(4)
  const c = Math.min(1, (idx * (MOVE + GAP) + MOVE + 0.45) / T).toFixed(4)
  const dur = `${T.toFixed(2)}s`
  return (
    <g aria-hidden="true">
      {dest && (
        <circle className={styles.ring} cx={dest[0]} cy={dest[1]} r={26} opacity={0}>
          <animate attributeName="r" dur={dur} repeatCount="2" values="26;26;46;46" keyTimes={`0;${b};${c};1`} />
          <animate attributeName="opacity" dur={dur} repeatCount="2" values="0;0;0.7;0;0" keyTimes={`0;${b};${b};${c};1`} />
        </circle>
      )}
      <circle className={styles.ball} r={7} opacity={0}>
        <animateMotion dur={dur} repeatCount="2" calcMode="linear" path={path} keyPoints="0;0;1;1" keyTimes={`0;${a};${b};1`} />
        <animate attributeName="opacity" dur={dur} repeatCount="2" calcMode="discrete" values="0;1;0" keyTimes={`0;${a};${b}`} />
      </circle>
    </g>
  )
}

function Pill({ x, y, text, k }: { x: number; y: number; text: string; k: number }) {
  const h = 22 * k
  const w = textWidth(text, 13 * k) + 14 * k
  return (
    <g>
      <rect className={styles.rolePill} x={x - w / 2} y={y - h / 2} width={w} height={h} rx={h / 2} />
      <text className={styles.roleText} x={x} y={y + 4.5 * k} textAnchor="middle">
        {text}
      </text>
    </g>
  )
}

export type StepMapProps = {
  guide: GuideFile
  step: GuideStep
  stepIndex: number
  // 좁은 화면이면 모바일 배치(nodes_mobile)를 쓴다.
  narrow: boolean
  reducedMotion: boolean
  // 화면 읽기 프로그램이 읽는 설명(경로와 메시지).
  label: string
}

export function StepMap({ guide, step, stepIndex, narrow, reducedMotion, label }: StepMapProps) {
  const useMobile = narrow && guide.map.nodes_mobile !== undefined && guide.map.view_mobile !== undefined
  const view = useMobile && guide.map.view_mobile ? guide.map.view_mobile : guide.map.view
  const nodes: GuideNode[] = useMobile && guide.map.nodes_mobile ? guide.map.nodes_mobile : guide.map.nodes
  const k = Math.max(1, view[0] / 640)
  const arrows = mapArrows(guide, nodes)
  const others = arrows.filter((m) => m.stepIndex !== stepIndex)
  const current = arrows.filter((m) => m.stepIndex === stepIndex)
  const moving = current.filter((m) => !m.arrow.local)
  const roles = stepRoles(step)
  const byId = new Map(nodes.map((n) => [n.id, n]))

  return (
    <svg
      className={styles.mapSvg}
      viewBox={`0 0 ${view[0]} ${view[1]}`}
      role="img"
      aria-label={label}
      style={{ '--k': k } as CSSProperties}
    >
      <IsoGrid w={view[0]} h={view[1]} />
      {others.map((m) => (
        <g key={`o-${m.stepIndex}-${m.arrowIndex}`} aria-hidden="true">
          <path className={styles.routeLine} d={curvePath(m)} />
          <Badge at={at(m, 0.5)} text={String(m.stepIndex + 1)} current={false} />
        </g>
      ))}
      {current.map((m) => {
        const mark = orderMark(m.arrow.label) ?? String(stepIndex + 1)
        const badgeAt = at(m, current.length > 1 ? 0.5 : 0.62)
        if (m.arrow.style === 'lost') {
          const part = partialPath(m, 0.55)
          const d = tangent(m, 0.55)
          const x: P = [part.end[0] + d[0] * 14, part.end[1] + d[1] * 14]
          return (
            <g key={`c-${m.arrowIndex}`} aria-hidden="true">
              <path className={styles.currentLine} d={part.d} />
              <path className={styles.lostMark} d={`M${x[0] - 7} ${x[1] - 7} L${x[0] + 7} ${x[1] + 7} M${x[0] + 7} ${x[1] - 7} L${x[0] - 7} ${x[1] + 7}`} />
              <Badge at={at(m, 0.3)} text={mark} current />
            </g>
          )
        }
        return (
          <g key={`c-${m.arrowIndex}`} aria-hidden="true">
            <path className={m.arrow.local ? styles.localLine : styles.currentLine} d={curvePath(m)} />
            <ArrowHead tip={m.p1} dir={tangent(m, 1)} />
            <Badge at={badgeAt} text={mark} current />
            {m.arrow.style === 'risk' && <Pill x={at(m, 0.3)[0]} y={at(m, 0.3)[1] - 18} text="위험" k={1} />}
          </g>
        )
      })}
      {!reducedMotion &&
        moving.map((m, idx) => {
          const lost = m.arrow.style === 'lost'
          const to = byId.get(m.arrow.to)
          const dest: P | null = lost || !to ? null : [to.x + 60, to.y + 24]
          return <Ball key={`b-${m.arrowIndex}`} path={lost ? partialPath(m, 0.55).d : curvePath(m)} idx={idx} total={moving.length} dest={dest} />
        })}
      {nodes.map((n) => {
        const on = step.active.includes(n.id)
        const cx = n.x + 60
        const note = step.notes[n.id]
        const labelY = n.y + 60 + 16 * k
        const subY = labelY + 17 * k
        return (
          <g key={n.id} className={on ? undefined : styles.nodeOff}>
            <NodeIcon icon={n.icon} cx={cx} y={n.y} />
            {roles[n.id] && <Pill x={cx} y={n.y - 14 * k} text={roles[n.id]} k={k} />}
            <text className={styles.nodeLabel} x={cx} y={labelY} textAnchor="middle">
              {n.label}
            </text>
            <text className={styles.nodeSub} x={cx} y={subY} textAnchor="middle">
              {n.sub}
            </text>
            {note && (
              <text className={styles.nodeNote} x={cx} y={subY + 18 * k} textAnchor="middle">
                {note}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}
