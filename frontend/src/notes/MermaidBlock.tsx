import { useEffect, useId, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { describeDiagram, readColors, renderDiagram } from './mermaid.ts'
import styles from './NoteBody.module.css'

// 화면 문구. 목업에 없는 임시 문구이며 확정되면 이 한 곳만 고친다(PR에 "문구 미정, 임시 문구"로 기록).
const MESSAGES = {
  drawing: '다이어그램을 그리는 중이에요',
}

type MermaidBlockProps = {
  source: string
  // 그림을 만들 수 없을 때(문법 오류 등) 대신 보이는 원래 코드 블록
  fallback: ReactNode
}

type Result = { source: string; url: string | null }

// 노트 본문의 mermaid 코드 블록을 그림으로 보인다. 그리는 동안은 안내를, 실패하면 원래 코드 블록을 보인다.
export function MermaidBlock({ source, fallback }: MermaidBlockProps) {
  const [result, setResult] = useState<Result | null>(null)
  // 이 블록이 놓인 자리의 디자인 토큰 값으로 그린다(예: data-theme="dark" 안에서는 어두운 토큰).
  const place = useRef<HTMLDivElement>(null)

  useEffect(() => {
    // 이 블록이 화면에 있는 동안, 그리고 같은 내용일 때만 결과를 쓴다.
    let alive = true
    renderDiagram(source, readColors(place.current ?? document.documentElement)).then(
      (url) => {
        if (alive) setResult({ source, url })
      },
      () => {
        if (alive) setResult({ source, url: null })
      },
    )
    return () => {
      alive = false
    }
  }, [source])

  const descriptionId = useId()
  const text = describeDiagram(source)
  const shown = result?.source === source ? result : null
  if (shown?.url === null) return <>{fallback}</>
  if (shown === null) return <div ref={place} className={styles.diagramPending} role="status">{MESSAGES.drawing}</div>
  // 이름(alt)은 짧게, 전체 원문은 눈에 보이지 않는 설명으로 이어 스크린 리더가 읽을 수 있게 한다.
  return <div ref={place} className={styles.diagram}>
    <img src={shown.url} alt={text.label} aria-describedby={descriptionId} />
    <span id={descriptionId} hidden>{text.description}</span>
  </div>
}
