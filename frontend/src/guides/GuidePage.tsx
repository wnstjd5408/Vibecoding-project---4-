// 단계별 지도 가이드 한 편을 보여 주는 화면 본문 (MEG-287, PRD v0.5 AC-1~AC-6).
// 경로 등록·닫기·노트 연결·플래그는 MEG-288에서 붙인다. 이 컴포넌트는 가이드 파일 하나를 받아 그린다.
import { Component, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { useWideLayout } from '../components/useWideLayout.ts'
import { useReducedMotion } from './useReducedMotion.ts'
import { cx } from '../components/cx.ts'
import { CompareFigure } from './CompareFigure.tsx'
import { SequenceDiagram } from './SequenceDiagram.tsx'
import { StepMap } from './StepMap.tsx'
import { followCallout, guideViews, sequenceLines, showsSequence, type GuideView } from './model.ts'
import type { GuideFile } from './types.ts'
import styles from './Guide.module.css'

// 지도·그림을 그리다 실패하면 그 자리를 비우지 않고 통째로 숨긴다(PRD AC-5). 글은 그대로 남는다.
class DrawingBoundary extends Component<{ onFail: () => void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  componentDidCatch() {
    this.props.onFail()
  }
  render() {
    return this.state.failed ? null : this.props.children
  }
}

// 개발 미리보기와 시험(MEG-289)에서 지도 실패를 일부러 일으킬 때 쓴다.
function FailingDrawing(): ReactNode {
  throw new Error('지도 그리기 실패(시험용)')
}

const MAP_NOTE = '아이콘의 자리는 모든 단계에서 그대로예요. 진한 실선과 번호 상자는 지금 단계, 회색 얇은 실선과 번호는 전체 경로예요. 무엇이 오가는지는 아래 상자에 적었어요.'
const SEQ_NOTE = '위에서 아래로 시간 순서예요. 선 모양은 오가는 것의 종류이고, 왼쪽 번호는 그 내용을 설명한 단계예요.'

export type GuidePageProps = {
  guide: GuideFile
  // 화면 위쪽 막대(닫기 등). MEG-288에서 경로에 붙일 때 넣는다.
  header?: ReactNode
  // 시험용: 지도 그리기를 일부러 실패시킨다.
  forceMapFailure?: boolean
}

export function GuidePage({ guide, header, forceMapFailure = false }: GuidePageProps) {
  const views = guideViews(guide)
  const [index, setIndex] = useState(0)
  const [replay, setReplay] = useState(0)
  const [mapFailed, setMapFailed] = useState(false)
  const wide = useWideLayout()
  const reducedMotion = useReducedMotion()
  const titleRef = useRef<HTMLHeadingElement>(null)
  const moved = useRef(false)
  const prevRef = useRef<HTMLButtonElement>(null)
  const nextRef = useRef<HTMLButtonElement>(null)

  const view: GuideView = views[Math.min(index, views.length - 1)]
  const stepCount = guide.steps.length
  const last = index === views.length - 1
  const sequenceHere = showsSequence(guide, view)
  const seq = guide.sequence
  const step = view.kind === 'step' ? view.step : null
  const appendix = view.kind === 'appendix' ? seq?.appendix : undefined
  const callout = step ? followCallout(guide, step) : { route: appendix?.callout.route ?? '', message: appendix?.callout.msg ?? '', ordered: false }
  const nextIsAppendix = views[index + 1]?.kind === 'appendix'
  const figure = step?.figure ? guide.figures[step.figure] : undefined

  // 단계를 넘겼을 때 새 단계 제목이 화면 밖이면 제목으로 올린다(본문이 한 화면보다 길 수 있어서).
  useLayoutEffect(() => {
    if (!moved.current) return
    moved.current = false
    const t = titleRef.current
    if (!t) return
    const r = t.getBoundingClientRect()
    if (r.top < 0 || r.top > window.innerHeight - 40) t.scrollIntoView({ block: 'start', behavior: reducedMotion ? 'auto' : 'smooth' })
  }, [index, reducedMotion])

  const go = (n: number) => {
    if (n < 0 || n >= views.length || n === index) return
    moved.current = true
    // 누른 버튼이 막히게 되면(첫·마지막 칸) 포커스를 반대쪽 버튼으로 옮겨 키보드 사용자가 길을 잃지 않게 한다(PRD AC-4).
    const active = document.activeElement
    if (n === views.length - 1 && active === nextRef.current) prevRef.current?.focus({ preventScroll: true })
    if (n === 0 && active === prevRef.current) nextRef.current?.focus({ preventScroll: true })
    setIndex(n)
    setReplay(0)
  }

  const chipLabel = (v: GuideView) => (v.kind === 'appendix' ? `부록 ${seq?.appendix?.short ?? ''}` : `${v.index + 1} ${v.step.short}`)
  const showMap = !mapFailed

  const mapColumn = showMap && (
    <div className={styles.mapColumn}>
      <DrawingBoundary key={`${index}-${replay}`} onFail={() => setMapFailed(true)}>
        {forceMapFailure && <FailingDrawing />}
        <div className={cx(styles.stage, !wide && (sequenceHere || !guide.map.nodes_mobile) && styles.stageScroll)}>
          {sequenceHere && seq ? (
            <SequenceDiagram sequence={seq} title={guide.title} />
          ) : step ? (
            <StepMap guide={guide} step={step} stepNumber={view.index + 1} narrow={!wide} reducedMotion={reducedMotion} />
          ) : null}
        </div>
        <p className={styles.stageNote}>{sequenceHere ? (seq?.note ?? SEQ_NOTE) : MAP_NOTE}</p>
        {!sequenceHere && !reducedMotion && step && step.arrows.some((a) => !a.local) && (
          <button type="button" className={styles.replay} onClick={() => setReplay((r) => r + 1)}>
            움직임 다시 보기
          </button>
        )}
      </DrawingBoundary>
    </div>
  )

  return (
    <div className={styles.page}>
      {header}
      <main className={cx(styles.wrap, showMap && styles.wrapWide)}>
        <h1 className={styles.title}>{guide.title}</h1>
        <p className={styles.scene}>
          {guide.scene} {guide.note}
        </p>
        <div className={cx(styles.split, showMap && styles.splitWithMap)}>
          {mapColumn}
          <div className={styles.textColumn}>
            <div className={styles.callout}>
              <span className={styles.calloutEyebrow}>
                {view.kind === 'appendix' ? '부록에서 모은 것' : showMap ? '전체 지도에서 따라가기' : '이 단계에서 오가는 것'}
              </span>
              <strong className={styles.calloutRoute}>{callout.route}</strong>
              <span className={styles.calloutMessage}>{callout.message}</span>
            </div>
            {callout.ordered && <p className={styles.orderNote}>①②③은 이 단계 안에서 일어나는 순서예요.</p>}
            <div className={styles.chips} role="group" aria-label="단계 고르기">
              {views.map((v, n) => (
                <button
                  key={n}
                  type="button"
                  className={styles.chip}
                  aria-current={n === index ? 'step' : undefined}
                  onClick={() => go(n)}
                >
                  {chipLabel(v)}
                </button>
              ))}
            </div>
            <section className={styles.step} aria-labelledby="guide-step-title" aria-live="polite">
              <div className={styles.meta}>
                {step ? `${step.kind} · ${view.index + 1} / ${stepCount}단계` : '부록'}
              </div>
              <h2 id="guide-step-title" ref={titleRef} className={styles.stepTitle}>
                {step ? step.title : appendix?.title}
              </h2>
              {(step ? step.body : (appendix?.body ?? [])).map((t, i) => (
                <p key={i} className={styles.body}>
                  {t}
                </p>
              ))}
              {figure && showMap && (
                <DrawingBoundary key={`fig-${index}`} onFail={() => undefined}>
                  <CompareFigure panels={figure} />
                </DrawingBoundary>
              )}
              {step?.aside && (
                <aside className={styles.termAside} aria-label="용어 설명">
                  <div className={styles.termEyebrow}>용어 설명</div>
                  <strong className={styles.termTitle}>{step.aside.title}</strong>
                  <p className={styles.termBody}>{step.aside.body}</p>
                </aside>
              )}
              {sequenceHere && (
                <div className={cx(styles.flow, view.kind === 'appendix' && styles.flowPlain)}>
                  <h3 className={styles.subheading}>전체 흐름 한눈에 보기</h3>
                  <ol>
                    {sequenceLines(guide).map((line, i) => (
                      <li key={i}>{line}</li>
                    ))}
                  </ol>
                </div>
              )}
              {step && step.changed.length > 0 && (
                <>
                  <h3 className={styles.subheading}>무엇이 바뀌었나</h3>
                  <ul className={styles.changed}>
                    {step.changed.map((t, i) => (
                      <li key={i}>{t}</li>
                    ))}
                  </ul>
                </>
              )}
            </section>
            <div className={styles.nav}>
              <button ref={prevRef} type="button" className={styles.navButton} disabled={index === 0} onClick={() => go(index - 1)}>
                이전
              </button>
              <span className={styles.spacer} />
              <button ref={nextRef} type="button" className={cx(styles.navButton, styles.navNext)} disabled={last} onClick={() => go(index + 1)}>
                {nextIsAppendix ? '부록 보기' : '다음'}
              </button>
            </div>
            {last && <p className={styles.end}>{guide.end_text ?? '이 가이드는 여기까지예요.'}</p>}
          </div>
        </div>
      </main>
    </div>
  )
}
