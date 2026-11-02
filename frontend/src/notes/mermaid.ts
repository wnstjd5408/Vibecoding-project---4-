// mermaid 다이어그램을 그림(SVG 데이터 주소)으로 만든다.
// - mermaid는 처음 필요할 때만 불러온다(지연 로드). mermaid가 없는 노트는 코드를 내려받지 않는다.
// - 본문은 HTML로 해석하지 않는 화면이라, 만든 SVG를 문서에 끼워 넣지 않고 <img>의 데이터 주소로만 보인다.
//   <img>로 그린 SVG는 스크립트와 이벤트 처리기가 실행되지 않는다. securityLevel strict와 아래 정리는 그 위의 이중 방어다.
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

// SVG 글자를 정리해 데이터 주소로 만든다. 크기는 viewBox의 숫자로 정해 <img>가 그림 비율대로 줄어들게 한다.
function toDataUrl(svg: string): string {
  const doc = new DOMParser().parseFromString(svg, 'image/svg+xml')
  const root = doc.documentElement
  if (root.nodeName !== 'svg' || doc.getElementsByTagName('parsererror').length > 0) throw new Error('invalid svg')
  for (const script of Array.from(doc.getElementsByTagName('script'))) script.remove()
  for (const element of Array.from(doc.getElementsByTagName('*'))) {
    for (const attribute of Array.from(element.attributes)) {
      if (/^on/i.test(attribute.name)) element.removeAttribute(attribute.name)
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
    const mermaid = await (api ??= import('mermaid').then((module) => module.default))
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
    await mermaid.parse(source)
    const id = `mermaid-diagram-${++counter}`
    const { svg } = await mermaid.render(id, source)
    // mermaid가 그리는 동안 문서에 만들어 두는 임시 요소가 남지 않게 한다.
    document.getElementById(id)?.remove()
    document.getElementById(`d${id}`)?.remove()
    return toDataUrl(svg)
  }
  const result = queue.then(run)
  queue = result.catch(() => undefined)
  return result
}
