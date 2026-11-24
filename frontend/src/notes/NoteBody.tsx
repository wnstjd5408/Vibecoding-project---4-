import { Fragment, useMemo } from 'react'
import type { ReactNode } from 'react'
import { fromMarkdown } from 'mdast-util-from-markdown'
import { gfmTableFromMarkdown } from 'mdast-util-gfm-table'
import { gfmTable } from 'micromark-extension-gfm-table'
import type { Nodes, PhrasingContent, Root, RootContent } from 'mdast'
import type { NoteReadResponse } from '../api/types.ts'
import { TermLink } from '../components/TermLink.tsx'
import { MermaidBlock } from './MermaidBlock.tsx'
import styles from './NoteBody.module.css'
import { SRC_ATTR, SRC_END_ATTR, UNMAPPED_ATTR } from './selection.ts'
import { alignText } from './sourceMap.ts'
import type { Piece } from './sourceMap.ts'
import { prepareSpans, splitBySpans } from './spans.ts'
import type { Span } from './spans.ts'

export const NOTE_IMAGE_SCHEME = 'note-image:'

type Context = {
  body: string
  spans: Span[]
  images: NoteReadResponse['images']
  // 불러오지 못해 글자로 대신 보이는 이미지 토큰
  brokenImages: ReadonlySet<string>
  // 용어를 눌렀을 때 부른다. 누른 링크를 함께 넘겨, 패널을 닫을 때 그 링크로 포커스를 돌려줄 수 있게 한다.
  onTerm: (termId: number, link: HTMLElement) => void
  onImageError: (token: string, failedUrl: string) => void
  // PC 사이드 패널과 이을 때(aria-controls)와 지금 열린 용어(aria-expanded). 바텀시트(모바일)에서는 주지 않는다.
  panelId?: string
  expandedTermId?: number | null
  // AI 모드(CS Agent 답변). 있으면 아래 ai 분기만 탄다. 노트 모드에서는 undefined라 기존 동작 그대로다.
  ai?: AiOptions
}

type AiOptions = {
  // 인용 번호 [n]을 출처 버튼으로 바꾼다. null을 돌려주면(출처에 없는 번호) [n]을 글자 그대로 둔다.
  citation: (ref: number) => ReactNode | null
}

// 인용 번호. 서버의 인용 검사(agent_output.citations)와 같은 모양이다(1~3자리 숫자).
const CITATION = /\[(\d{1,3})\]/g

// AI 모드 본문(docs/architecture.md 5절 "출력 처리 — CS Agent 답변"). 노트 렌더러의 구문 트리 처리를 그대로 쓰고 아래만 다르다.
// 링크는 <a> 없이 글자만, 이미지 문법은 대체 글만(주소를 불러오지 않는다), 용어 링크와 data-note-body·원문 위치 속성은 없음,
// HTML은 글자 그대로, mermaid 코드 블록은 코드로만, 인용 [n]은 citation이 돌려준 출처 버튼으로 그린다.
type AiNoteBodyProps = {
  mode: 'ai'
  body: string
  citation: AiOptions['citation']
}

type NoteModeProps = {
  mode?: 'note'
  body: string
  spans: NoteReadResponse['glossary_spans']
  images: NoteReadResponse['images']
  brokenImages: ReadonlySet<string>
  onTerm: (termId: number, link: HTMLElement) => void
  onImageError: (token: string, failedUrl: string) => void
  // PC 폭에서 용어 링크를 사이드 패널과 잇는다: 패널 id(aria-controls)와 지금 패널에 열린 용어(aria-expanded)
  panelId?: string
  expandedTermId?: number | null
  // 시트 안 설명처럼 작은 글자로 그린다. 노트 본문이 아니라서 선택 위치 계산 대상(data-note-body)에서 뺀다.
  compact?: boolean
}

type NoteBodyProps = NoteModeProps | AiNoteBodyProps

const NO_SPANS: NoteReadResponse['glossary_spans'] = []
const NO_IMAGES: NoteReadResponse['images'] = {}
const NO_BROKEN: ReadonlySet<string> = new Set()
const noop = () => {}

// 노트 본문을 마크다운 구문 트리로 읽어 React 요소로 그린다. 본문은 HTML로 해석하지 않는다.
// 본문 속 HTML은 글자 그대로 보이고, dangerouslySetInnerHTML은 쓰지 않는다.
// 글자 조각마다 원문 위치를 data 속성으로 달아 두어(selection.ts) 드래그한 범위를 원문 위치로 바꿀 수 있다.
// mode="ai"는 CS Agent 답변용 AI 모드다(AiNoteBodyProps 설명).
export function NoteBody(props: NoteBodyProps) {
  const { body } = props
  const spans = props.mode === 'ai' ? NO_SPANS : props.spans
  const tree = useMemo(() => fromMarkdown(body, {
    extensions: [gfmTable()], mdastExtensions: [gfmTableFromMarkdown()],
  }), [body])
  const prepared = useMemo(() => prepareSpans(body, spans), [body, spans])
  if (props.mode === 'ai') {
    const context: Context = { body, spans: [], images: NO_IMAGES, brokenImages: NO_BROKEN, onTerm: noop, onImageError: noop, ai: { citation: props.citation } }
    return <div className={styles.body}>{blocks(tree, context)}</div>
  }
  const { images, brokenImages, onTerm, onImageError, panelId, expandedTermId, compact = false } = props
  const context: Context = { body, spans: prepared, images, brokenImages, onTerm, onImageError, panelId, expandedTermId }
  return <div className={compact ? `${styles.body} ${styles.compact}` : styles.body} {...(compact ? {} : { 'data-note-body': '' })}>{blocks(tree, context)}</div>
}

// AI 모드의 글자: 원문 위치 속성 없이 글자만 두고, 인용 [n]만 출처 버튼으로 바꾼다.
function aiText(value: string, ai: AiOptions): ReactNode {
  const out: ReactNode[] = []
  let last = 0
  for (const match of value.matchAll(CITATION)) {
    const button = ai.citation(Number(match[1]))
    if (button === null) continue
    if (match.index > last) out.push(value.slice(last, match.index))
    out.push(<Fragment key={match.index}>{button}</Fragment>)
    last = match.index + match[0].length
  }
  if (last === 0) return value
  if (last < value.length) out.push(value.slice(last))
  return out
}

// AI 모드에서 마크다운 문법으로 해석하지 않을 노드(참조 링크, 링크 정의)는 원문 글자 그대로 보인다.
function aiSource(node: Nodes, body: string, ai: AiOptions): ReactNode {
  const [start, end] = offsets(node)
  return aiText(body.slice(start, end), ai)
}

// AI 모드의 링크는 글자만 보인다. 다만 글자가 숫자 하나뿐인 링크([1](주소))는 서버가 인용 [1]로 센 것이라 인용으로 그린다.
function aiLink(node: Extract<Nodes, { type: 'link' }>, context: Context, ai: AiOptions): ReactNode {
  const [only] = node.children
  if (node.children.length === 1 && only.type === 'text' && /^\d{1,3}$/.test(only.value)) return aiText(`[${only.value}]`, ai)
  return inline(node.children, context)
}

function blocks(parent: Root | Extract<Nodes, { children: unknown[] }>, context: Context): ReactNode {
  return (parent.children as RootContent[]).map((node, index) => <Fragment key={index}>{block(node, context)}</Fragment>)
}

function inline(nodes: PhrasingContent[], context: Context): ReactNode {
  return nodes.map((node, index) => <Fragment key={index}>{phrasing(node, context)}</Fragment>)
}

// 글자 조각을 그린다. pieces가 null이면 위치를 계산하지 못한 글자라 표시만 한다.
function segments(value: string, pieces: Piece[] | null, context: Context): ReactNode {
  if (context.ai) return aiText(value, context.ai)
  if (pieces === null) return <span {...{ [UNMAPPED_ATTR]: '' }}>{value}</span>
  return splitBySpans(pieces, context.spans).map((segment) => {
    const attrs: Record<string, string | number> = { [SRC_ATTR]: segment.srcStart }
    if (!segment.exact) attrs[SRC_END_ATTR] = segment.srcEnd
    const termId = segment.termId
    return termId === undefined
      ? <span key={segment.srcStart} {...attrs}>{segment.text}</span>
      : <TermLink key={segment.srcStart} href={`#term-${termId}`} data-term-id={termId} onClick={(event) => context.onTerm(termId, event.currentTarget)}
          {...(context.panelId === undefined ? null : { 'aria-expanded': context.expandedTermId === termId, 'aria-controls': context.panelId })} {...attrs}>{segment.text}</TermLink>
  })
}

function offsets(node: { position?: { start: { offset?: number }; end: { offset?: number } } }): [number, number] {
  return [node.position?.start.offset ?? 0, node.position?.end.offset ?? 0]
}

function textOf(node: Nodes & { value: string }, context: Context): ReactNode {
  const [start, end] = offsets(node)
  return segments(node.value, alignText(node.value, context.body.slice(start, end), start), context)
}

// 인라인 코드: 앞뒤 백틱을 떼고, 파서가 앞뒤 공백 하나씩을 뗀 경우를 맞춘다.
function inlineCodeOf(node: Extract<Nodes, { type: 'inlineCode' }>, context: Context): ReactNode {
  // AI 모드: 코드 안의 [n]은 인용이 아니다(서버 인용 검사도 코드를 뺀다).
  if (context.ai) return <code>{node.value}</code>
  const [start, end] = offsets(node)
  const match = /^(`+)([\s\S]*?)\1$/.exec(context.body.slice(start, end))
  let pieces: Piece[] | null = null
  if (match) {
    const innerStart = start + match[1].length
    const inner = match[2]
    const padded = inner.length > 2 && inner.startsWith(' ') && inner.endsWith(' ') && node.value === inner.slice(1, -1)
    pieces = padded
      ? alignText(node.value, inner.slice(1, -1), innerStart + 1)
      : alignText(node.value, inner, innerStart)
  }
  return <code>{segments(node.value, pieces, context)}</code>
}

// 코드 블록: 울타리(```) 코드 블록은 첫 줄 다음부터가 내용이다. 들여쓴 코드 블록은 줄마다 공백이 빠져 위치를 계산하지 않는다.
function codeBlockOf(node: Extract<Nodes, { type: 'code' }>, context: Context): ReactNode {
  // AI 모드: 언어가 mermaid여도 그림으로 그리지 않고 코드로만 보인다. 그림은 figures[]로만 받는다.
  if (context.ai) return <pre><code>{node.value}</code></pre>
  const [start, end] = offsets(node)
  const source = context.body.slice(start, end)
  const firstLine = source.indexOf('\n')
  const contentStart = firstLine < 0 ? -1 : start + firstLine + 1
  const fenced = /^(`{3,}|~{3,})/.test(source) && contentStart >= 0 && context.body.startsWith(node.value, contentStart)
  const pieces: Piece[] | null = node.value === ''
    ? []
    : fenced ? [{ text: node.value, srcStart: contentStart, srcEnd: contentStart + node.value.length, exact: true }] : null
  const code = <pre><code>{segments(node.value, pieces, context)}</code></pre>
  // 언어 표시가 mermaid인 울타리는 보기 방식(다이어그램만·코드만·둘 다)에 따라 그림과 원래 코드 블록을 보인다.
  if (node.lang?.trim().toLowerCase() === 'mermaid') return <MermaidBlock source={node.value} fallback={code} />
  return code
}

function safeHref(url: string): string | null {
  return /^(https?:|mailto:)/i.test(url) ? url : null
}

function phrasing(node: PhrasingContent, context: Context): ReactNode {
  switch (node.type) {
    case 'text':
    case 'html':
      return textOf(node, context)
    case 'strong':
      return <strong>{inline(node.children, context)}</strong>
    case 'emphasis':
      return <em>{inline(node.children, context)}</em>
    case 'inlineCode':
      return inlineCodeOf(node, context)
    case 'break':
      return <br />
    case 'link': {
      // AI 모드: 주소와 관계없이 <a>를 만들지 않고 링크 글자만 보인다.
      if (context.ai) return aiLink(node, context, context.ai)
      const href = safeHref(node.url)
      return href
        ? <a href={href} target="_blank" rel="noopener noreferrer">{inline(node.children, context)}</a>
        : <>{inline(node.children, context)}</>
    }
    case 'linkReference':
      // AI 모드: 본문에 [n]: 정의가 있으면 [n]이 참조 링크가 된다. 마크다운으로 해석하지 않고 원문 글자로 보여 인용 [n]을 살린다.
      if (context.ai) return aiSource(node, context.body, context.ai)
      return <>{inline(node.children, context)}</>
    case 'image':
      // AI 모드: 주소와 관계없이 불러오지 않고 대체 글만 보인다.
      if (context.ai) return <>{node.alt ?? ''}</>
      return image(node.url, node.alt ?? '', context)
    case 'imageReference':
      return <>{node.alt ?? ''}</>
    default:
      return null
  }
}

// note-image:토큰을 images 맵의 URL로 바꿔 그린다. 맵에 없거나 불러오지 못한 이미지는 대체 글로 보인다.
function image(url: string, alt: string, context: Context): ReactNode {
  if (!url.startsWith(NOTE_IMAGE_SCHEME)) return <span className={styles.imageFallback}>{alt}</span>
  const token = url.slice(NOTE_IMAGE_SCHEME.length)
  const entry = context.images[token]
  if (!entry || context.brokenImages.has(token)) {
    return <span className={styles.imageFallback} role="img" aria-label={alt || entry?.alt || '이미지'}>이미지를 불러오지 못했어요{alt ? ` (${alt})` : ''}</span>
  }
  return <img className={styles.image} src={entry.url} alt={alt || entry.alt} loading="lazy" onError={() => context.onImageError(token, entry.url)} />
}

function block(node: RootContent, context: Context): ReactNode {
  switch (node.type) {
    case 'table': {
      const [header, ...rows] = node.children
      const cells = (row: typeof header, heading: boolean) => row.children.map((cell, index) => {
        const Cell = heading ? 'th' : 'td'
        return <Cell key={index} scope={heading ? 'col' : undefined} style={{ textAlign: node.align?.[index] ?? undefined }}>{inline(cell.children, context)}</Cell>
      })
      return <div className={styles.tableScroll}><table>
        {header && <thead><tr>{cells(header, true)}</tr></thead>}
        <tbody>{rows.map((row, index) => <tr key={index}>{cells(row, false)}</tr>)}</tbody>
      </table></div>
    }
    case 'paragraph':
      return <p>{inline(node.children, context)}</p>
    case 'heading': {
      // 화면 제목(노트 제목)이 h1이라 본문 제목은 한 단계 낮춘다.
      // AI 모드는 답변 절 제목(h3, AiAnswer) 아래에 놓이므로 세 단계 낮춘다(# → h4).
      const Heading = `h${Math.min(node.depth + (context.ai ? 3 : 1), 6)}` as 'h2'
      return <Heading>{inline(node.children, context)}</Heading>
    }
    case 'blockquote':
      return <blockquote>{blocks(node, context)}</blockquote>
    case 'list': {
      const List = node.ordered ? 'ol' : 'ul'
      return <List start={node.ordered && node.start != null && node.start !== 1 ? node.start : undefined}>{blocks(node, context)}</List>
    }
    case 'listItem':
      return <li>{blocks(node, context)}</li>
    case 'code':
      return codeBlockOf(node, context)
    case 'html':
      return <p>{textOf(node, context)}</p>
    case 'thematicBreak':
      return <hr />
    case 'definition':
      // AI 모드: 링크 정의([n]: 주소)를 지우지 않고 글자 그대로 보인다. 노트 모드는 지금처럼 보이지 않는다.
      return context.ai ? <p>{aiSource(node, context.body, context.ai)}</p> : null
    default:
      return null
  }
}
