import { useEffect, useId, useRef, useState } from 'react'
import type { KeyboardEvent, ReactNode } from 'react'
import { describeDiagram, readColors, renderDiagram } from './mermaid.ts'
import styles from './NoteBody.module.css'

// 화면 문구. 목업에 없는 임시 문구이며 확정되면 이 한 곳만 고친다(PR에 "문구 미정, 임시 문구"로 기록).
const MESSAGES = {
  drawing: '다이어그램을 그리는 중이에요',
  syntaxError: 'Mermaid 문법 오류로 다이어그램을 표시할 수 없어요.',
  modeGroup: 'Mermaid 보기 방식',
}

// 보기 방식. 기본은 다이어그램만이고, 블록마다 따로 고르며 저장하지 않는다(새로고침·노트 이동 때 기본값으로 돌아간다).
type Mode = 'diagram' | 'code' | 'both'
const MODES: ReadonlyArray<{ mode: Mode; label: string }> = [
  { mode: 'diagram', label: '다이어그램만' },
  { mode: 'code', label: '코드만' },
  { mode: 'both', label: '둘 다' },
]

type MermaidBlockProps = {
  source: string
  // 원문 코드를 보이는 원래 코드 블록. 용어 링크·선택 위치 계산을 그대로 쓰도록 이 조각을 재사용한다.
  fallback: ReactNode
}

type Result = { source: string; url: string | null }

// 노트 본문의 mermaid 코드 블록을 보기 방식(다이어그램만·코드만·둘 다)에 따라 보인다.
// 문법 오류로 그림을 만들 수 없으면 다이어그램 자리에 안내를 보이고, 원문은 코드만·둘 다 방식에서만 보인다.
// 방식 선택은 그림을 그리는 중이든 오류든 늘 남아 있어서, 오류 안내를 본 사용자가 바로 코드로 바꿀 수 있다.
export function MermaidBlock({ source, fallback }: MermaidBlockProps) {
  const [mode, setMode] = useState<Mode>('diagram')
  const [result, setResult] = useState<Result | null>(null)
  // 가장 최근에 그린 결과. 방식을 바꿔 다시 그림을 보일 때 같은 내용을 또 그리지 않는다.
  const drawn = useRef<Result | null>(null)
  // 이 블록이 놓인 자리의 디자인 토큰 값으로 그린다(예: data-theme="dark" 안에서는 어두운 토큰).
  const place = useRef<HTMLDivElement>(null)
  const options = useRef<Array<HTMLButtonElement | null>>([])
  const wantsDiagram = mode !== 'code'

  useEffect(() => {
    // 코드만 방식에서는 그림을 그리지 않는다(그리기 비용을 아끼고, 오류 여부도 모른 채 원문을 보인다).
    if (!wantsDiagram || drawn.current?.source === source) return
    // 이 블록이 화면에 있는 동안, 그리고 같은 내용일 때만 결과를 쓴다.
    let alive = true
    const settle = (url: string | null) => {
      if (!alive) return
      drawn.current = { source, url }
      setResult(drawn.current)
    }
    renderDiagram(source, readColors(place.current ?? document.documentElement)).then(settle, () => settle(null))
    return () => {
      alive = false
    }
  }, [source, wantsDiagram])

  const descriptionId = useId()
  const text = describeDiagram(source)
  const shown = result?.source === source ? result : null

  // 라디오 그룹: Tab으로는 선택된 항목 하나만 들어가고, 방향키로 고르며, 고른 항목으로 포커스를 옮긴다.
  const choose = (index: number) => {
    const next = (index + MODES.length) % MODES.length
    setMode(MODES[next].mode)
    options.current[next]?.focus()
  }
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') choose(index + 1)
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') choose(index - 1)
    else if (event.key === 'Home') choose(0)
    else if (event.key === 'End') choose(MODES.length - 1)
    else return
    event.preventDefault()
  }

  let diagram: ReactNode = null
  if (wantsDiagram) {
    if (shown === null) diagram = <div className={styles.diagramPending} role="status">{MESSAGES.drawing}</div>
    else if (shown.url === null) diagram = <div className={styles.diagramPending} role="status">{MESSAGES.syntaxError}</div>
    else {
      // 이름(alt)은 짧게, 전체 원문은 눈에 보이지 않는 설명으로 이어 스크린 리더가 읽을 수 있게 한다.
      diagram = <div className={styles.diagram}>
        <img src={shown.url} alt={text.label} aria-describedby={descriptionId} />
        <span id={descriptionId} hidden>{text.description}</span>
      </div>
    }
  }

  return <div ref={place}>
    <div role="radiogroup" aria-label={MESSAGES.modeGroup} className={styles.modeGroup}>
      {MODES.map(({ mode: value, label }, index) => <button
        key={value}
        ref={(element) => { options.current[index] = element }}
        type="button"
        role="radio"
        aria-checked={mode === value}
        tabIndex={mode === value ? 0 : -1}
        className={styles.modeOption}
        onClick={() => setMode(value)}
        onKeyDown={(event) => onKeyDown(event, index)}
      >{label}</button>)}
    </div>
    {diagram}
    {mode === 'diagram' ? null : fallback}
  </div>
}
