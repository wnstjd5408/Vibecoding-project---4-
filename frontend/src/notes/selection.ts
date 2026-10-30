// 렌더된 본문에서 드래그한 범위를 원문(body_markdown) 위치로 바꾼다(MEG-74, Q-N3). AI 설명 요청(E09)이 이 값을 쓴다.
// NoteBody가 글자 조각마다 단 data 속성을 읽는다.
//  - data-src="시작": 글자가 원문과 같은 조각. 조각 안 위치가 원문 위치와 1:1이다.
//  - data-src + data-src-end: 글자 수가 달라 한 덩어리로만 대응하는 조각(이스케이프·엔티티). 끝점은 덩어리 경계로 밀어낸다.
//  - data-src-unmapped: 위치를 계산하지 못하는 글자(들여쓴 코드 블록 등). 여기에 걸치면 null이다.

export const SRC_ATTR = 'data-src'
export const SRC_END_ATTR = 'data-src-end'
export const UNMAPPED_ATTR = 'data-src-unmapped'

export type SourceRange = { start: number; end: number }

const MAPPED = `[${SRC_ATTR}],[${UNMAPPED_ATTR}]`

function mappedTextNodes(root: Element): Text[] {
  const nodes: Text[] = []
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (node.parentElement?.closest(MAPPED) && root.contains(node.parentElement.closest(MAPPED))) nodes.push(node as Text)
  }
  return nodes
}

// 글자 노드 안 위치(offset)를 원문 위치로 바꾼다. edge는 이 위치가 선택의 시작인지 끝인지다.
function locate(node: Text, offset: number, edge: 'start' | 'end'): number | null {
  const element = node.parentElement?.closest(MAPPED)
  if (!element || element.hasAttribute(UNMAPPED_ATTR)) return null
  const start = Number(element.getAttribute(SRC_ATTR))
  const endAttr = element.getAttribute(SRC_END_ATTR)
  if (endAttr === null) return start + offset
  const end = Number(endAttr)
  if (offset <= 0) return start
  if (offset >= node.length) return end
  return edge === 'start' ? start : end
}

// 선택 범위의 원문 위치 [start, end)를 돌려준다. 본문 밖이거나 비었거나 위치를 알 수 없는 글자에 걸치면 null이다.
export function sourceRangeOfSelection(root: Element, range: Range): SourceRange | null {
  if (range.collapsed) return null
  const texts = mappedTextNodes(root)
  const first = texts.find((node) => range.comparePoint(node, node.length) >= 0)
  const last = [...texts].reverse().find((node) => range.comparePoint(node, 0) <= 0)
  if (!first || !last) return null
  const startOffset = range.comparePoint(first, 0) >= 0 ? 0 : range.startOffset
  const endOffset = range.comparePoint(last, last.length) <= 0 ? last.length : range.endOffset
  // 시작·끝 사이에 위치를 알 수 없는 글자가 끼어 있으면 범위를 확정할 수 없다.
  const between = texts.slice(texts.indexOf(first), texts.indexOf(last) + 1)
  if (between.some((node) => node.parentElement?.closest(MAPPED)?.hasAttribute(UNMAPPED_ATTR))) return null
  const start = locate(first, startOffset, 'start')
  const end = locate(last, endOffset, 'end')
  if (start === null || end === null || start >= end) return null
  return { start, end }
}
