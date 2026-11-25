// 아이콘 비교 그림 (MEG-287, MEG-270 요소 9). 단계 글 아래에 그림 칸을 하나 이상 나란히 둔다.
import { NodeIcon } from './StepMap.tsx'
import type { GuideFigurePanel } from './types.ts'
import styles from './Guide.module.css'

function Panel({ panel }: { panel: GuideFigurePanel }) {
  const [W, H] = panel.view
  const byId = new Map(panel.nodes.map((n) => [n.id, n]))
  const grid = []
  for (let k = 0; k <= 8; k++) {
    const x = (W / 8) * k
    grid.push(<line key={`v${k}`} x1={x - 60} y1={H} x2={x + 60} y2={40} />)
    grid.push(<line key={`h${k}`} x1={0} y1={40 + ((H - 40) / 8) * k} x2={W} y2={40 + ((H - 40) / 8) * k - 30} />)
  }
  return (
    <svg className={styles.figureSvg} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${panel.title}. ${panel.desc}`}>
      <g className={styles.grid} aria-hidden="true">
        {grid}
      </g>
      <text className={styles.figureTitle} x={16} y={26} aria-hidden="true">
        {panel.title}
      </text>
      {panel.edges.map((e, i) => {
        const a = byId.get(e.from)
        const b = byId.get(e.to)
        if (!a || !b) throw new Error(`그림에 없는 노드: ${e.from} → ${e.to}`)
        const [x1, y1] = [a.x, a.y + 24]
        const [x2, y2] = [b.x, b.y + 24]
        const len = Math.hypot(x2 - x1, y2 - y1) || 1
        const ux = (x2 - x1) / len
        const uy = (y2 - y1) / len
        // oy: 같은 두 노드 사이의 왕복 화살표가 한 선으로 겹치지 않게 위아래로 띄운다.
        const oy = e.oy ?? 0
        const sx = x1 + ux * 48
        const sy = y1 + uy * 48 + oy
        const ex = x2 - ux * 48
        const ey = y2 - uy * 48 + oy
        const nx = -uy
        const ny = ux
        const bx = ex - ux * 11
        const by = ey - uy * 11
        return (
          <g key={i} aria-hidden="true">
            <line
              className={e.faint ? styles.figureFaint : styles.figureLine}
              x1={sx}
              y1={sy}
              x2={ex - (e.faint ? 0 : ux * 8)}
              y2={ey - (e.faint ? 0 : uy * 8)}
            />
            {!e.faint && <polygon className={styles.currentHead} points={[ex, ey, bx + nx * 5.5, by + ny * 5.5, bx - nx * 5.5, by - ny * 5.5].join(' ')} />}
            {e.label && (
              <text
                className={styles.figureEdgeLabel}
                x={e.lx ?? (sx + ex) / 2}
                y={e.ly ?? Math.min(sy, ey) - 34}
                textAnchor={e.lx !== undefined ? 'start' : 'middle'}
              >
                {e.label}
              </text>
            )}
          </g>
        )
      })}
      {panel.nodes.map((n) => (
        <g key={n.id} className={n.off ? styles.figureOff : undefined} aria-hidden="true">
          <NodeIcon icon={n.icon} cx={n.x} y={n.y} />
          <text className={styles.figureNodeLabel} x={n.x} y={n.y + 78} textAnchor="middle">
            {n.label}
          </text>
          <text className={styles.figureNodeSub} x={n.x} y={n.y + 97} textAnchor="middle">
            {n.sub}
          </text>
        </g>
      ))}
      {panel.notes.map((nt, i) => (
        <text key={i} className={styles.figureNote} x={nt.x} y={nt.y} textAnchor="middle" aria-hidden="true">
          {nt.text}
        </text>
      ))}
    </svg>
  )
}

export function CompareFigure({ panels }: { panels: GuideFigurePanel[] }) {
  return (
    <div className={styles.figure}>
      {panels.map((p, i) => (
        <Panel key={i} panel={p} />
      ))}
    </div>
  )
}
