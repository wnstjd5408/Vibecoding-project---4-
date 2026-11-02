// 렌더된 본문에서 드래그한 범위를 원문(body_markdown) 위치로 바꾼다(MEG-74, Q-N3). AI 설명 요청(E09)이 이 값을 쓴다.
// NoteBody가 글자 조각마다 단 data 속성을 읽는다.
//  - data-src="시작": 글자가 원문과 같은 조각. 조각 안 위치가 원문 위치와 1:1이다.
//  - data-src + data-src-end: 글자 수가 달라 한 덩어리로만 대응하는 조각(이스케이프·엔티티). 끝점은 덩어리 경계로 밀어낸다.
//  - data-src-unmapped: 위치를 계산하지 못하는 글자(들여쓴 코드 블록 등). 여기에 걸치면 null이다.
// 선택이 본문 밖이나 속성이 없는 글자(이미지 대체 문구 등)에 걸쳐도 null이다. 본문 부분만 잘라 돌려주지 않는다.

export const SRC_ATTR = 'data-src'
export const SRC_END_ATTR = 'data-src-end'
export const UNMAPPED_ATTR = 'data-src-unmapped'

export type SourceRange = { start: number; end: number }

const MAPPED = `[${SRC_ATTR}],[${UNMAPPED_ATTR}]`

function textNodes(root: Element): Text[] {
  const nodes: Text[] = []
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  for (let node = walker.nextNode(); node; node = walker.nextNode()) nodes.push(node as Text)
  return nodes
}

// 원문 위치를 가진 글자인지. 속성이 없거나 위치를 모른다고 표시된 글자는 아니다.
function isMapped(node: Text, root: Element): boolean {
  const element = node.parentElement?.closest(MAPPED)
  return element !== null && element !== undefined && root.contains(element) && !element.hasAttribute(UNMAPPED_ATTR)
}

// 선택이 이 글자 노드에서 실제로 덮는 구간 [from, to). 걸치지 않거나 겹치는 글자가 없으면 null이다.
function covered(range: Range, node: Text): [number, number] | null {
  if (range.comparePoint(node, node.length) < 0 || range.comparePoint(node, 0) > 0) return null
  // 시작점이 이 노드 안이면(시작 컨테이너가 이 노드) 시작 offset, 아니면 노드 처음부터다. 끝도 같다.
  const from = range.comparePoint(node, 0) >= 0 ? 0 : range.startOffset
  const to = range.comparePoint(node, node.length) <= 0 ? node.length : range.endOffset
  return from < to ? [from, to] : null
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

// 선택 범위의 원문 위치 [start, end)를 돌려준다.
// 비었거나, 끝점이 본문 밖이거나, 선택이 덮는 글자 중 원문 위치를 모르는 것이 하나라도 있으면 null이다.
export function sourceRangeOfSelection(root: Element, range: Range): SourceRange | null {
  if (range.collapsed) return null
  if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) return null
  const parts: { node: Text; from: number; to: number }[] = []
  for (const node of textNodes(root)) {
    const part = covered(range, node)
    if (part) parts.push({ node, from: part[0], to: part[1] })
  }
  if (parts.length === 0 || parts.some((part) => !isMapped(part.node, root))) return null
  const first = parts[0]
  const last = parts[parts.length - 1]
  const start = locate(first.node, first.from, 'start')
  const end = locate(last.node, last.to, 'end')
  if (start === null || end === null || start >= end) return null
  return { start, end }
}
