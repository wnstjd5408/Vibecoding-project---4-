// 전체 흐름 시퀀스 다이어그램 (MEG-287, MEG-270 요소 10). 위에서 아래로 시간 순서이고,
// 선 모양은 보호 수준·요청/응답, 왼쪽 번호는 그 내용을 설명한 단계다. 생명선은 얇은 실선이다(PRD v0.5 5.6절 5번).
import { textWidth } from './model.ts'
import type { GuideSequence } from './types.ts'
import styles from './Guide.module.css'

// 선 모양 이름 → 굵기. 정해진 세 이름 밖은 보통 굵기로 그린다.
const LINE_CLASS: Record<string, string> = { plain: styles.seqPlain, hs: styles.seqHandshake, app: styles.seqApp }

export function SequenceDiagram({ sequence, title }: { sequence: GuideSequence; title: string }) {
  const actors = sequence.actors
  const W = 770
  const TOP = 84
  const GAP = 46
  const rows = sequence.rows
  const X: Record<string, number> = {}
  actors.forEach((a, i) => {
    X[a.id] = actors.length === 2 ? [190, 640][i] : 110 + (i * (W - 190)) / (actors.length - 1)
  })
  const boxW = actors.length === 2 ? 140 : Math.min(140, (W - 190) / (actors.length - 1) - 16)
  const XL = X[actors[0].id]
  const XR = X[actors[actors.length - 1].id]
  const H = TOP + rows.length * GAP + 64
  const ly = H - 26

  return (
    <svg className={styles.seqSvg} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title} 전체 흐름 시퀀스 다이어그램. 같은 내용을 아래 글 목록으로도 읽을 수 있어요.`}>
      {actors.map((a) => (
        <g key={a.id} aria-hidden="true">
          <line className={styles.seqLife} x1={X[a.id]} y1={54} x2={X[a.id]} y2={H - 54} />
          <rect className={styles.seqActor} x={X[a.id] - boxW / 2} y={16} width={boxW} height={38} rx={6} />
          <text className={styles.seqActorText} x={X[a.id]} y={40} textAnchor="middle">
            {a.name}
          </text>
        </g>
      ))}
      {rows.map((r, n) => {
        const y = TOP + n * GAP
        const stepBox = (
          <>
            <rect className={styles.seqStep} x={14} y={y - 11} width={22} height={22} rx={4} />
            <text className={styles.seqStepText} x={25} y={y + 4.5} textAnchor="middle">
              {r.step}
            </text>
          </>
        )
        if (r.k === 'msg') {
          const x1 = X[r.from]
          const x2 = X[r.to]
          const dir = Math.sign(x2 - x1)
          const lw = textWidth(r.label, 13) + 10
          return (
            <g key={n} aria-hidden="true">
              {stepBox}
              <line className={LINE_CLASS[r.prot] ?? styles.seqPlain} x1={x1} y1={y} x2={x2 - dir * 10} y2={y} />
              <polygon className={styles.seqHead} points={[x2, y, x2 - dir * 12, y - 6, x2 - dir * 12, y + 6].join(' ')} />
              {/* 참여자가 셋 이상이면 이름표가 가운데 생명선과 겹치므로 바탕을 깐다. */}
              {actors.length > 2 && <rect className={styles.seqLabelBg} x={(x1 + x2) / 2 - lw / 2} y={y - 23} width={lw} height={18} rx={3} />}
              <text className={styles.seqLabel} x={(x1 + x2) / 2} y={y - 9} textAnchor="middle">
                {r.label}
              </text>
              <text className={styles.seqTag} x={(x1 + x2) / 2} y={y + 19} textAnchor="middle">
                {sequence.tags[r.prot]}
              </text>
            </g>
          )
        }
        const w = Math.max(textWidth(r.label, 12) + 24, 120)
        const both = r.at === 'both'
        const cx = both ? (XL + XR) / 2 : Math.min(Math.max(X[r.at], 48 + w / 2), W - 8 - w / 2)
        const ww = both ? Math.max(w, XR - XL + 60) : w
        return (
          <g key={n} aria-hidden="true">
            {stepBox}
            <rect className={styles.seqNote} x={cx - ww / 2} y={y - 13} width={ww} height={26} rx={4} />
            <text className={styles.seqNoteText} x={cx} y={y + 4} textAnchor="middle">
              {r.label}
            </text>
          </g>
        )
      })}
      {sequence.legend.map(([p, txt], n) => {
        const x = 60 + n * (sequence.legend.length === 2 ? 345 : 230)
        return (
          <g key={p} aria-hidden="true">
            <line className={LINE_CLASS[p] ?? styles.seqPlain} x1={x} y1={ly} x2={x + 46} y2={ly} />
            <text className={styles.seqTag} x={x + 56} y={ly + 4}>
              {txt}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
