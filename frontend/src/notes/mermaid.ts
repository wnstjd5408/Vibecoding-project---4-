// mermaid 다이어그램을 그림(SVG 데이터 주소)으로 만든다.
// - mermaid는 처음 필요할 때만 불러온다(지연 로드). mermaid가 없는 노트는 코드를 내려받지 않는다.
// - 본문은 HTML로 해석하지 않는 화면이라, 만든 SVG를 문서에 끼워 넣지 않고 <img>의 데이터 주소로만 보인다.
//   <img>로 그린 SVG는 스크립트와 이벤트 처리기가 실행되지 않는다. 이것이 보안의 핵심이다.
//   securityLevel strict는 라벨의 HTML을 글자로 바꾸고, 아래 정리는 사용자가 이미지를 새 탭에서 따로 열었을 때를 위한 보조 방어다.
type MermaidApi = typeof import('mermaid').default

let api: Promise<MermaidApi> | null = null
// mermaid가 한 번에 하나씩만 그리게 해 한 노트의 여러 블록이 서로 방해하지 않게 한다.
let queue: Promise<unknown> = Promise.resolve()
let counter = 0

// 다이어그램 색은 화면의 디자인 토큰(밝은·어두운 화면 모두)을 그대로 따른다. 그림자·그라데이션은 쓰지 않는다.
export type DiagramColors = { ink: string; muted: string; paper: string; ground: string; border: string; rule: string }

export function readColors(place: Element): DiagramColors {
  const style = getComputedStyle(place)
  const read = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback
  return {
    ink: read('--ink', '#16202f'),
    muted: read('--ink-muted', '#566474'),
    paper: read('--surface-200', '#ffffff'),
    ground: read('--surface-100', '#f5f6f8'),
    border: read('--line-strong', '#76818f'),
    rule: read('--surface-300', '#dde2e9'),
  }
}

function themeVariables(colors: DiagramColors) {
  return {
    fontFamily: 'sans-serif',
    background: colors.paper,
    mainBkg: colors.paper,
    primaryColor: colors.paper,
    primaryTextColor: colors.ink,
    primaryBorderColor: colors.border,
    secondaryColor: colors.ground,
    secondaryTextColor: colors.ink,
    secondaryBorderColor: colors.border,
    tertiaryColor: colors.ground,
    tertiaryTextColor: colors.ink,
    tertiaryBorderColor: colors.border,
    textColor: colors.ink,
    lineColor: colors.muted,
    nodeBorder: colors.border,
    nodeTextColor: colors.ink,
    clusterBkg: colors.ground,
    clusterBorder: colors.rule,
    edgeLabelBackground: colors.paper,
    titleColor: colors.ink,
    noteBkgColor: colors.ground,
    noteTextColor: colors.ink,
    noteBorderColor: colors.border,
    actorBkg: colors.paper,
    actorBorder: colors.border,
    actorTextColor: colors.ink,
    actorLineColor: colors.muted,
    signalColor: colors.ink,
    signalTextColor: colors.ink,
    labelBoxBkgColor: colors.paper,
    labelBoxBorderColor: colors.border,
    labelTextColor: colors.ink,
    loopTextColor: colors.ink,
  }
}

// 노트 작성자가 설정 지시문(%%{init: …}%%)·머리말(--- config: … ---)·스타일 문법으로 모양·테마·색을 바꾸지 못하게 지운다.
// 모양과 색은 디자인 토큰으로 고정한다. 그림은 스타일만 빠진 채 그려지고, 코드로 돌아가지 않는다.
// 지우는 것: 설정 지시문, 머리말(title 같은 설정이 아닌 값도 함께 사라진다), classDef·linkStyle·style·cssClass 줄,
//   노드에 클래스를 붙이는 `class A,B name` 줄(클래스 다이어그램의 `class Foo`·`class Foo {`는 인자가 하나라 그대로 둔다), `:::name`,
//   시퀀스 다이어그램 `rect`·`box`에 지정한 색.
// 알려진 한계: `box Aqua 이름`처럼 색 이름을 쓴 경우와 mermaid가 앞으로 더하는 스타일 문법은 지우지 못한다.
export function withoutStyle(source: string): string {
  return source
    .replace(/%%\{[\s\S]*?\}%%/g, '')
    .replace(/^\s*---\r?\n[\s\S]*?\r?\n---[ \t]*(\r?\n|$)/, '')
    .split(/\r?\n/)
    // 한 줄에 `;`로 이어 쓴 문장(`graph TD; A --> B; style A fill:#f00;`)도 문장마다 검사한다.
    // 문장은 따옴표·괄호 밖의 `;`에서만 나누므로 라벨 안의 `;`는 그대로 남고, 지우는 문장 말고는 원문 그대로 다시 이어 붙인다.
    .map((line) => statementsOf(line).filter((statement) => !isStyleStatement(statement)).map(cleanStatement).join(';'))
    .join('\n')
}

// 줄을 따옴표("…")와 괄호([…]·(…)·{…}) 밖의 `;`에서 나눈다. 마지막 조각은 `;` 뒤의 나머지(없으면 빈 글)다.
function statementsOf(line: string): string[] {
  const parts: string[] = []
  let depth = 0
  let quoted = false
  let start = 0
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index]
    if (char === '"') quoted = !quoted
    else if (quoted) continue
    else if (char === '[' || char === '(' || char === '{') depth += 1
    else if (depth > 0 && (char === ']' || char === ')' || char === '}')) depth -= 1
    else if (char === ';' && depth === 0) {
      parts.push(line.slice(start, index))
      start = index + 1
    }
  }
  parts.push(line.slice(start))
  return parts
}

function isStyleStatement(statement: string): boolean {
  return /^\s*(classDef|linkStyle|style|cssClass)\s/.test(statement) || /^\s*class\s+\S+\s+[^\s{<~":;]+\s*$/.test(statement)
}

function cleanStatement(statement: string): string {
  return statement
    .replace(/:::[^\s;,)\]}]+/g, '')
    .replace(/^(\s*rect\s+).*$/, '$1transparent')
    .replace(/^(\s*box\s+)(?:rgba?\([^)]*\)|#[0-9a-fA-F]{3,8})\s*/, '$1')
}

// 그려진 그림의 접근 가능한 이름과 설명. 그림이 되면 원래 코드(노드 이름·관계)가 사라지므로 전체 원문을 설명에 남긴다(자르지 않는다).
// 이름은 짧게 두고(Mermaid의 accTitle이 있으면 반영), 설명에 accDescr와 원문을 한 줄로 이어 담는다. 설명은 눈에 보이지 않게 aria-describedby로 잇는다.
export function describeDiagram(source: string): { label: string; description: string } {
  const text = withoutStyle(source)
  const title = /^\s*accTitle\s*:\s*(.+?)\s*$/m.exec(text)?.[1]
  const described = /^\s*accDescr\s*:\s*(.+?)\s*$/m.exec(text)?.[1] ?? /^\s*accDescr\s*\{([\s\S]*?)\}/m.exec(text)?.[1]?.replace(/\s+/g, ' ').trim()
  const flat = text.split('\n').map((line) => line.trim()).filter(Boolean).join('; ')
  return {
    label: title ? `mermaid 다이어그램: ${title}` : 'mermaid 다이어그램',
    description: [described, `원문: ${flat}`].filter(Boolean).join(' '),
  }
}

// SVG 글자를 정리해 데이터 주소로 만든다. 크기는 viewBox의 숫자로 정해 <img>가 그림 비율대로 줄어들게 한다.
function toDataUrl(svg: string): string {
  const doc = new DOMParser().parseFromString(svg, 'image/svg+xml')
  const root = doc.documentElement
  if (root.nodeName !== 'svg' || doc.getElementsByTagName('parsererror').length > 0) throw new Error('invalid svg')
  for (const script of Array.from(doc.getElementsByTagName('script'))) script.remove()
  for (const element of Array.from(doc.getElementsByTagName('*'))) {
    for (const attribute of Array.from(element.attributes)) {
      if (/^on/i.test(attribute.name)) element.removeAttribute(attribute.name)
      // 이미지를 새 탭에서 따로 열면 SVG가 문서로 열릴 수 있어 javascript: 링크도 지운다.
      else if (/href$/i.test(attribute.name) && /^\s*javascript:/i.test(attribute.value)) element.removeAttribute(attribute.name)
    }
  }
  const box = (root.getAttribute('viewBox') ?? '').trim().split(/[\s,]+/).map(Number)
  if (box.length === 4 && box.every(Number.isFinite) && box[2] > 0 && box[3] > 0) {
    root.setAttribute('width', String(box[2]))
    root.setAttribute('height', String(box[3]))
    root.removeAttribute('style')
  }
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(new XMLSerializer().serializeToString(root))}`
}

// 문법이 틀리거나 그릴 수 없으면 거부한다. 부르는 쪽이 원래 코드 블록으로 돌아간다.
export function renderDiagram(source: string, colors: DiagramColors): Promise<string> {
  const run = async () => {
    // 불러오기가 한 번 실패해도(네트워크 순단 등) 그 실패를 붙들어 두지 않고 다음 블록이 다시 시도하게 한다.
    const mermaid = await (api ??= import('mermaid').then((module) => module.default, (error: unknown) => {
      api = null
      throw error
    }))
    // 디자인 규칙: 그림자·그라데이션을 쓰지 않는다. 기본 모양(neo)은 그림자 필터를 쓰므로 classic으로 둔다.
    // 다이어그램 종류마다 자기 설정에 look 기본값이 있어 최상위 look만으로는 바뀌지 않는다. look을 가진 종류를 모두 classic으로 맞춘다.
    const looks = Object.fromEntries(
      Object.entries(mermaid.mermaidAPI.defaultConfig as Record<string, unknown>)
        .filter(([, value]) => typeof value === 'object' && value !== null && 'look' in value)
        .map(([name]) => [name, { look: 'classic' }]),
    )
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      suppressErrorRendering: true,
      theme: 'base',
      look: 'classic',
      themeVariables: themeVariables(colors),
      htmlLabels: false,
      ...looks,
      flowchart: { htmlLabels: false, look: 'classic' },
    })
    const text = withoutStyle(source)
    await mermaid.parse(text)
    const id = `mermaid-diagram-${++counter}`
    const { svg } = await mermaid.render(id, text)
    // mermaid가 그리는 동안 문서에 만들어 두는 임시 요소가 남지 않게 한다.
    document.getElementById(id)?.remove()
    document.getElementById(`d${id}`)?.remove()
    return toDataUrl(svg)
  }
  const result = queue.then(run)
  queue = result.catch(() => undefined)
  return result
}
