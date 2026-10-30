import type { Piece } from './sourceMap.ts'
import { toUtf16Index } from './sourceMap.ts'

// E05 glossary_spans를 UTF-16 위치로 바꾼 것. 끝은 포함하지 않는다.
export type Span = { termId: number; start: number; end: number }

// 렌더할 글자 조각. termId가 있으면 사전 용어(형광펜)다.
export type Segment = Piece & { termId?: number }

// 서버 값(코드포인트, [start, end))을 UTF-16으로 바꾼다. 범위를 벗어나거나 비었거나 앞 용어와 겹치는 것은 버린다.
export function prepareSpans(body: string, spans: { term_id: number; start: number; end: number }[]): Span[] {
  const converted: Span[] = []
  for (const span of spans) {
    const start = toUtf16Index(body, span.start)
    const end = toUtf16Index(body, span.end)
    if (start === null || end === null || start >= end) continue
    converted.push({ termId: span.term_id, start, end })
  }
  converted.sort((a, b) => a.start - b.start || a.end - b.end)
  const kept: Span[] = []
  for (const span of converted) {
    if (kept.length > 0 && span.start < kept[kept.length - 1].end) continue
    kept.push(span)
  }
  return kept
}

// 글자 조각을 용어 경계에서 자른다. 글자가 원문과 같은 조각(exact)은 경계에서 글자 단위로 자르고,
// 같지 않은 조각은 쪼갤 수 없어 용어와 조금이라도 겹치면 통째로 용어로 본다.
export function splitBySpans(pieces: Piece[], spans: Span[]): Segment[] {
  const out: Segment[] = []
  for (const piece of pieces) {
    const overlapping = spans.filter((span) => span.start < piece.srcEnd && span.end > piece.srcStart)
    if (overlapping.length === 0) {
      out.push(piece)
      continue
    }
    if (!piece.exact) {
      out.push({ ...piece, termId: overlapping[0].termId })
      continue
    }
    let cursor = piece.srcStart
    for (const span of overlapping) {
      const from = Math.max(span.start, piece.srcStart)
      const to = Math.min(span.end, piece.srcEnd)
      if (from > cursor) out.push({ text: piece.text.slice(cursor - piece.srcStart, from - piece.srcStart), srcStart: cursor, srcEnd: from, exact: true })
      out.push({ text: piece.text.slice(from - piece.srcStart, to - piece.srcStart), srcStart: from, srcEnd: to, exact: true, termId: span.termId })
      cursor = to
    }
    if (cursor < piece.srcEnd) out.push({ text: piece.text.slice(cursor - piece.srcStart), srcStart: cursor, srcEnd: piece.srcEnd, exact: true })
  }
  return out
}
