import { Fragment, useMemo } from 'react'
import type { ReactNode } from 'react'
import { fromMarkdown } from 'mdast-util-from-markdown'
import { gfmTableFromMarkdown } from 'mdast-util-gfm-table'
import { gfmTable } from 'micromark-extension-gfm-table'
import type { Nodes, PhrasingContent, Root, RootContent } from 'mdast'
import type { NoteReadResponse } from '../api/types.ts'
import { TermLink } from '../components/TermLink.tsx'
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
  onTerm: (termId: number) => void
  onImageError: (token: string, failedUrl: string) => void
}

type NoteBodyProps = {
  body: string
  spans: NoteReadResponse['glossary_spans']
  images: NoteReadResponse['images']
  brokenImages: ReadonlySet<string>
  onTerm: (termId: number) => void
  onImageError: (token: string, failedUrl: string) => void
  // 시트 안 설명처럼 작은 글자로 그린다. 노트 본문이 아니라서 선택 위치 계산 대상(data-note-body)에서 뺀다.
  compact?: boolean
}

// 노트 본문을 마크다운 구문 트리로 읽어 React 요소로 그린다. 본문은 HTML로 해석하지 않는다.
// 본문 속 HTML은 글자 그대로 보이고, dangerouslySetInnerHTML은 쓰지 않는다.
// 글자 조각마다 원문 위치를 data 속성으로 달아 두어(selection.ts) 드래그한 범위를 원문 위치로 바꿀 수 있다.
export function NoteBody({ body, spans, images, brokenImages, onTerm, onImageError, compact = false }: NoteBodyProps) {
  const tree = useMemo(() => fromMarkdown(body, {
    extensions: [gfmTable()], mdastExtensions: [gfmTableFromMarkdown()],
  }), [body])
  const prepared = useMemo(() => prepareSpans(body, spans), [body, spans])
  const context: Context = { body, spans: prepared, images, brokenImages, onTerm, onImageError }
  return <div className={compact ? `${styles.body} ${styles.compact}` : styles.body} {...(compact ? {} : { 'data-note-body': '' })}>{blocks(tree, context)}</div>
}

function blocks(parent: Root | Extract<Nodes, { children: unknown[] }>, context: Context): ReactNode {
  return (parent.children as RootContent[]).map((node, index) => <Fragment key={index}>{block(node, context)}</Fragment>)
}

function inline(nodes: PhrasingContent[], context: Context): ReactNode {
  return nodes.map((node, index) => <Fragment key={index}>{phrasing(node, context)}</Fragment>)
}

// 글자 조각을 그린다. pieces가 null이면 위치를 계산하지 못한 글자라 표시만 한다.
function segments(value: string, pieces: Piece[] | null, context: Context): ReactNode {
  if (pieces === null) return <span {...{ [UNMAPPED_ATTR]: '' }}>{value}</span>
  return splitBySpans(pieces, context.spans).map((segment) => {
    const attrs: Record<string, string | number> = { [SRC_ATTR]: segment.srcStart }
    if (!segment.exact) attrs[SRC_END_ATTR] = segment.srcEnd
    const termId = segment.termId
    return termId === undefined
      ? <span key={segment.srcStart} {...attrs}>{segment.text}</span>
      : <TermLink key={segment.srcStart} href={`#term-${termId}`} data-term-id={termId} onClick={() => context.onTerm(termId)} {...attrs}>{segment.text}</TermLink>
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
  const [start, end] = offsets(node)
  const source = context.body.slice(start, end)
  const firstLine = source.indexOf('\n')
  const contentStart = firstLine < 0 ? -1 : start + firstLine + 1
  const fenced = /^(`{3,}|~{3,})/.test(source) && contentStart >= 0 && context.body.startsWith(node.value, contentStart)
  const pieces: Piece[] | null = node.value === ''
    ? []
    : fenced ? [{ text: node.value, srcStart: contentStart, srcEnd: contentStart + node.value.length, exact: true }] : null
  return <pre><code>{segments(node.value, pieces, context)}</code></pre>
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
      const href = safeHref(node.url)
      return href
        ? <a href={href} target="_blank" rel="noopener noreferrer">{inline(node.children, context)}</a>
        : <>{inline(node.children, context)}</>
    }
    case 'linkReference':
      return <>{inline(node.children, context)}</>
    case 'image':
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
      const Heading = `h${Math.min(node.depth + 1, 6)}` as 'h2'
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
    default:
      return null
  }
}
