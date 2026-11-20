import { Component, Fragment, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { readColors, renderDiagram } from './mermaid.ts'
import { NoteBody } from './NoteBody.tsx'
import styles from './AiAnswer.module.css'
import noteStyles from './NoteBody.module.css'

// CS Agent "AI에게 질문" 답변(E29 result의 sections·figures·sources)을 그린다(MEG-256, docs/architecture.md 5절).
// 아래 타입은 이 컴포넌트가 받는 값이다. API 응답 타입(MEG-255)과의 연결은 화면 연결(T6c)에서 한다.
// 패널 배치, AI 생성 상자, 단계 목록, 출처 보기 화면은 이 컴포넌트 밖(T6c)이다.

export type AiAnswerSection = {
  heading?: string
  // 제한된 마크다운(NoteBody AI 모드)으로 그린다. 인용 번호 [n]이 들어 있다.
  body: string
}

export type AiAnswerFigure = {
  figure_id: string
  // 노트 근거 기간(T4 전)에는 diagram만 온다. 그 밖의 종류는 그리지 않고 실패 카드로 보인다.
  kind: string
  mermaid?: string
  caption: string
  alt_text: string
  source_refs: number[]
  // 이 번호의 절(1부터) 바로 아래에 둔다. 범위를 벗어나면 마지막 절 아래에 둔다.
  after_section: number
}

export type AiAnswerSource = {
  ref: number
  source_kind: string
  title: string
  section?: string
}

type AiAnswerProps = {
  sections: AiAnswerSection[]
  figures?: AiAnswerFigure[]
  sources?: AiAnswerSource[]
  // 출처 버튼을 누르면 부른다. 누른 버튼을 함께 넘겨 출처 보기를 닫을 때 포커스를 돌려줄 수 있게 한다.
  onSource: (ref: number, button: HTMLButtonElement) => void
}

// 화면 문구. 목업(디자인 v0.2 14.5, F6-16·F6-18)에서 가져왔고, 목업에 없는 것은 임시 문구다(PR에 기록).
const MESSAGES = {
  // 확정: F6-18 캡션의 출처 앞 글(source_kind별, 노트 근거 기간 14.5)
  figureSourceLabel: (kind: string) => (kind === 'wiki' ? '위키 문단' : '노트 문단'),
  // 확정: S11 '그림을 표시하지 못했어요'와 14.2의 오류 머리 규칙
  figureFailed: '오류: 그림을 표시하지 못했어요',
  // 임시: 실패 카드에서 그림 설명 앞에 붙는 글
  figureFailedHelp: '그림 설명',
  // 임시: 그리는 중 안내
  figureDrawing: '그림을 그리는 중이에요',
  // 임시: 출처 버튼의 접근 가능한 이름
  citationLabel: (ref: number, title: string) => `출처 ${ref} 보기: ${title}`,
}

export function AiAnswer({ sections, figures = [], sources = [], onSource }: AiAnswerProps) {
  const byRef = new Map(sources.map((source) => [source.ref, source]))
  // 서버가 검증한 sources[]에 있는 번호만 버튼이 된다. 없는 번호는 [n] 글자 그대로 둔다.
  const citation = (ref: number): ReactNode | null => {
    const source = byRef.get(ref)
    if (!source) return null
    return <button type="button" className={styles.citation} aria-label={MESSAGES.citationLabel(ref, source.title)}
      onClick={(event) => onSource(ref, event.currentTarget)}>[{ref}]</button>
  }
  const last = sections.length
  const placeOf = (figure: AiAnswerFigure) => (Number.isInteger(figure.after_section) && figure.after_section >= 1 && figure.after_section <= last ? figure.after_section : last)
  // 그림 자리를 정하는 일은 경계(FigureBoundary) 밖에서 하므로, 객체가 아닌 항목은 여기서 빼서 답변 전체가 깨지지 않게 한다.
  const valid = figures.filter((figure): figure is AiAnswerFigure => typeof figure === 'object' && figure !== null)
  return <div className={styles.answer}>
    {sections.map((section, index) => <Fragment key={index}>
      <section className={styles.section}>
        {section.heading ? <h3 className={styles.heading}>{section.heading}</h3> : null}
        <NoteBody mode="ai" body={section.body} citation={citation} />
      </section>
      {valid.map((figure, order) => ({ figure, order })).filter(({ figure }) => placeOf(figure) === index + 1).map(({ figure, order }) => <FigureBoundary key={`${order}:${String(figure.figure_id)}`} figure={figure} citation={citation} sources={byRef}>
        <AiFigure figure={figure} citation={citation} sources={byRef} />
      </FigureBoundary>)}
    </Fragment>)}
  </div>
}

type FigureProps = {
  figure: AiAnswerFigure
  citation: (ref: number) => ReactNode | null
  sources: ReadonlyMap<number, AiAnswerSource>
}

type Drawn = { mermaid: string; url: string | null }

// 그림 하나. 노트와 같은 strict 설정(renderDiagram)으로 그리고, 결과 SVG는 <img>의 데이터 주소로만 보인다.
// 그리지 못하면 실패 카드로 바꾸고, 본문은 건드리지 않는다. '다시 그리기'는 두지 않는다(디자인 결정 2).
function AiFigure({ figure, citation, sources }: FigureProps) {
  const place = useRef<HTMLElement>(null)
  const mermaid = figure.kind === 'diagram' && typeof figure.mermaid === 'string' ? figure.mermaid : null
  const [drawn, setDrawn] = useState<Drawn | null>(null)

  useEffect(() => {
    if (mermaid === null) return
    let active = true
    renderDiagram(mermaid, readColors(place.current ?? document.documentElement)).then(
      (url) => { if (active) setDrawn({ mermaid, url }) },
      () => { if (active) setDrawn({ mermaid, url: null }) },
    )
    return () => { active = false }
  }, [mermaid])

  const shown = drawn?.mermaid === mermaid ? drawn : null
  if (mermaid === null || (shown !== null && shown.url === null)) return <FigureFailure figure={figure} citation={citation} sources={sources} />
  return <figure ref={place} className={styles.figure} data-figure-id={figure.figure_id}>
    {shown === null
      ? <div className={noteStyles.diagramPending} role="status">{MESSAGES.figureDrawing}</div>
      // 넓은 그림은 이 영역만 가로로 스크롤한다. 키보드로도 스크롤할 수 있게 포커스를 받는다.
      : <div className={`${noteStyles.diagram} ${styles.scroll}`} tabIndex={0} role="group" aria-label={figure.caption}>
          <img src={shown.url ?? undefined} alt={figure.alt_text} />
        </div>}
    <figcaption className={styles.caption}>
      {figure.caption}
      <FigureSources figure={figure} citation={citation} sources={sources} />
    </figcaption>
  </figure>
}

// 캡션 뒤 출처: "노트 문단 [1] [2]". 출처 종류가 섞이면 종류마다 따로 묶는다.
function FigureSources({ figure, citation, sources }: FigureProps) {
  const groups = new Map<string, number[]>()
  for (const ref of figure.source_refs) {
    const source = sources.get(ref)
    if (!source) continue
    groups.set(source.source_kind, [...(groups.get(source.source_kind) ?? []), ref])
  }
  if (groups.size === 0) return null
  return <span className={styles.captionSources}>
    {[...groups].map(([kind, refs]) => <span key={kind}>
      {MESSAGES.figureSourceLabel(kind)}{refs.map((ref) => <Fragment key={ref}> {citation(ref)}</Fragment>)}
    </span>)}
  </span>
}

// 그림 실패 카드. 그림 설명(alt_text)과 캡션, 캡션의 출처 버튼을 남겨 그림의 뜻과 근거를 읽을 수 있게 한다.
// 경계(FigureBoundary)의 대체 화면으로 쓸 때는 출처 버튼을 빼고(그리다 깨진 곳일 수 있다) 글만 남긴다.
function FigureFailure({ figure, citation, sources }: { figure: AiAnswerFigure } & Partial<Omit<FigureProps, 'figure'>>) {
  return <div className={styles.failure} role="note" data-figure-id={figure.figure_id} data-figure-failed="">
    <p className={styles.failureTitle}>{MESSAGES.figureFailed}</p>
    {/* 경계의 대체 화면으로도 쓰므로, 값이 글자가 아니어도 다시 깨지지 않게 글자로 바꾼다. */}
    <p className={styles.failureText}>
      {String(figure.caption ?? '')}
      {citation && sources ? <FigureSources figure={figure} citation={citation} sources={sources} /> : null}
    </p>
    <p className={styles.failureText}>{MESSAGES.figureFailedHelp}: {String(figure.alt_text ?? '')}</p>
  </div>
}

// 그림 하나를 그리다 예상하지 못한 오류가 나도 그 그림만 실패 카드로 바꾼다. 답변 본문과 패널의 다른 글(단계 목록 등)은 남는다.
// figure_id는 답변마다 f-1부터 다시 매기므로, 같은 자리에 다른 그림이 오면 실패 표시를 풀고 다시 그린다.
type BoundaryProps = FigureProps & { children: ReactNode }
type BoundaryState = { failed: boolean; figure: AiAnswerFigure }

class FigureBoundary extends Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = { failed: false, figure: this.props.figure }
  static getDerivedStateFromProps(props: BoundaryProps, state: BoundaryState): Partial<BoundaryState> | null {
    return props.figure === state.figure ? null : { failed: false, figure: props.figure }
  }
  static getDerivedStateFromError(): Partial<BoundaryState> {
    return { failed: true }
  }
  render() {
    return this.state.failed ? <FigureFailure figure={this.props.figure} /> : this.props.children
  }
}
