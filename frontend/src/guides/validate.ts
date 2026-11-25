// 가이드 파일과 목록 파일의 형식 검사 (MEG-286, PRD v0.5 AC-5·AC-7·AC-9).
// 브라우저와 Node(scripts/check-guides.ts) 양쪽에서 쓰도록 순수 함수로만 만든다.
import {
  GUIDE_ARROW_STYLES,
  GUIDE_ICONS,
  GUIDE_SCHEMA_VERSION,
  GUIDE_SEQUENCE_PLACEMENTS,
  GUIDE_STEP_KINDS,
  type GuideFile,
} from './types.ts'

export type GuideIssue = { path: string; message: string }

export type ValidateGuideOptions = {
  // 파일 이름에서 얻은 slug. 주면 파일 안의 slug와 같아야 한다.
  fileSlug?: string
  // 검수 전 초안 검사. review가 비어 있어도 통과시킨다(공개 목록에는 못 올린다).
  draft?: boolean
}

type Obj = Record<string, unknown>

const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/

const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v)
const isText = (v: unknown): v is string => typeof v === 'string' && v.trim().length > 0
const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const isInt = (v: unknown): v is number => Number.isInteger(v)
const oneOf = <T extends string>(list: readonly T[], v: unknown): v is T =>
  typeof v === 'string' && (list as readonly string[]).includes(v)
const show = (v: unknown) => (typeof v === 'string' ? `"${v}"` : JSON.stringify(v))
// `in`은 constructor 같은 프로토타입 키도 참으로 본다. 자기 키만 본다.
const hasKey = (o: Obj, k: unknown) => typeof k === 'string' && Object.hasOwn(o, k)
// 달력에 있는 날짜인지(2026-02-31 같은 값은 Date.parse가 다음 달로 넘겨 통과시킨다).
const isCalendarDate = (s: unknown) =>
  typeof s === 'string' && DATE_RE.test(s) && !Number.isNaN(Date.parse(s)) && new Date(s).toISOString().slice(0, 10) === s

// 알려진 키만 쓴다. 오타(stlye)나 생성기에서 딸려 온 필드가 공개 저장소에 조용히 들어가지 않게 한다.
const KEYS = {
  guide: ['schema_version', 'slug', 'title', 'scene', 'note', 'term_key', 'note_id', 'revision', 'review', 'end_text', 'map', 'steps', 'figures', 'sequence'],
  map: ['view', 'nodes', 'view_mobile', 'nodes_mobile'],
  node: ['id', 'x', 'y', 'icon', 'label', 'sub'],
  figureNode: ['id', 'x', 'y', 'icon', 'label', 'sub', 'off'],
  step: ['short', 'kind', 'title', 'body', 'changed', 'active', 'arrows', 'notes', 'roles', 'aside', 'figure'],
  arrow: ['from', 'to', 'label', 'local', 'style', 'shift'],
  review: ['reviewer', 'reviewed_on', 'sources', 'record_url'],
  sequence: ['placement', 'actors', 'tags', 'legend', 'note', 'rows', 'appendix'],
} as const

class Collector {
  issues: GuideIssue[] = []
  add(path: string, message: string) {
    this.issues.push({ path, message })
  }
  keys(o: Obj, allowed: readonly string[], base: string) {
    for (const k of Object.keys(o)) {
      if (!allowed.includes(k)) this.add(`${base}${base ? '.' : ''}${k}`, '알 수 없는 필드예요. 오타인지 확인해 주세요.')
    }
  }
  text(o: Obj, key: string, base: string) {
    if (!isText(o[key])) this.add(`${base}${key}`, '비어 있지 않은 글이어야 해요.')
  }
  textList(v: unknown, path: string, allowEmpty = false) {
    if (!Array.isArray(v) || (!allowEmpty && v.length === 0)) {
      this.add(path, allowEmpty ? '글 목록이어야 해요.' : '글이 하나 이상 있는 목록이어야 해요.')
      return
    }
    v.forEach((t, i) => {
      if (!isText(t)) this.add(`${path}[${i}]`, '비어 있지 않은 글이어야 해요.')
    })
  }
  view(v: unknown, path: string) {
    if (!Array.isArray(v) || v.length !== 2 || !v.every((n) => isNum(n) && n > 0)) {
      this.add(path, '[너비, 높이] 두 양수여야 해요.')
    }
  }
}

function checkNodes(c: Collector, v: unknown, path: string, allowOff: boolean): Set<string> {
  const ids = new Set<string>()
  if (!Array.isArray(v) || v.length === 0) {
    c.add(path, '노드가 하나 이상 있는 목록이어야 해요.')
    return ids
  }
  v.forEach((n, i) => {
    const p = `${path}[${i}]`
    if (!isObj(n)) {
      c.add(p, '노드 객체여야 해요.')
      return
    }
    c.keys(n, allowOff ? KEYS.figureNode : KEYS.node, p)
    if (!isText(n.id)) c.add(`${p}.id`, '비어 있지 않은 글이어야 해요.')
    else if (ids.has(n.id)) c.add(`${p}.id`, `${show(n.id)} 노드가 두 번 나와요.`)
    else ids.add(n.id)
    if (!isNum(n.x)) c.add(`${p}.x`, '숫자여야 해요.')
    if (!isNum(n.y)) c.add(`${p}.y`, '숫자여야 해요.')
    if (!oneOf(GUIDE_ICONS, n.icon)) c.add(`${p}.icon`, `${show(n.icon)}는 쓸 수 있는 아이콘이 아니에요. 쓸 수 있는 것: ${GUIDE_ICONS.join(', ')}`)
    c.text(n, 'label', `${p}.`)
    if (typeof n.sub !== 'string') c.add(`${p}.sub`, '글이어야 해요(빈 글은 괜찮아요).')
    if (allowOff && n.off !== undefined && typeof n.off !== 'boolean') c.add(`${p}.off`, 'true 또는 false여야 해요.')
  })
  return ids
}

function checkNodeKeys(c: Collector, v: unknown, path: string, ids: Set<string>, required: boolean) {
  if (v === undefined && !required) return
  if (!isObj(v)) {
    c.add(path, '노드 id를 키로 쓰는 객체여야 해요.')
    return
  }
  for (const [k, t] of Object.entries(v)) {
    if (!ids.has(k)) c.add(`${path}.${k}`, `${show(k)} 노드가 지도에 없어요.`)
    if (!isText(t)) c.add(`${path}.${k}`, '비어 있지 않은 글이어야 해요.')
  }
}

function checkFigures(c: Collector, v: unknown): Set<string> {
  const names = new Set<string>()
  if (!isObj(v)) {
    c.add('figures', '그림 이름을 키로 쓰는 객체여야 해요(그림이 없으면 {}).')
    return names
  }
  for (const [name, panels] of Object.entries(v)) {
    names.add(name)
    const base = `figures.${name}`
    if (!Array.isArray(panels) || panels.length === 0) {
      c.add(base, '그림 칸이 하나 이상 있는 목록이어야 해요.')
      continue
    }
    panels.forEach((panel, i) => {
      const p = `${base}[${i}]`
      if (!isObj(panel)) {
        c.add(p, '그림 칸 객체여야 해요.')
        return
      }
      c.text(panel, 'title', `${p}.`)
      // 그림을 못 보는 사람이 읽는 설명이다(접근성).
      c.text(panel, 'desc', `${p}.`)
      c.view(panel.view, `${p}.view`)
      const ids = checkNodes(c, panel.nodes, `${p}.nodes`, true)
      if (!Array.isArray(panel.edges)) c.add(`${p}.edges`, '목록이어야 해요(선이 없으면 []).')
      else
        panel.edges.forEach((e, j) => {
          const q = `${p}.edges[${j}]`
          if (!isObj(e)) return c.add(q, '선 객체여야 해요.')
          for (const end of ['from', 'to'] as const) {
            if (!ids.has(e[end] as string)) c.add(`${q}.${end}`, `${show(e[end])} 노드가 이 그림 칸에 없어요.`)
          }
          if (e.label !== undefined && !isText(e.label)) c.add(`${q}.label`, '비어 있지 않은 글이어야 해요.')
          for (const k of ['lx', 'ly', 'oy'] as const) {
            if (e[k] !== undefined && !isNum(e[k])) c.add(`${q}.${k}`, '숫자여야 해요.')
          }
          if (e.faint !== undefined && typeof e.faint !== 'boolean') c.add(`${q}.faint`, 'true 또는 false여야 해요.')
        })
      if (!Array.isArray(panel.notes)) c.add(`${p}.notes`, '목록이어야 해요(메모가 없으면 []).')
      else
        panel.notes.forEach((nt, j) => {
          const q = `${p}.notes[${j}]`
          if (!isObj(nt) || !isNum(nt.x) || !isNum(nt.y) || !isText(nt.text)) c.add(q, '{ x, y, text } 형식이어야 해요.')
        })
    })
  }
  return names
}

function checkReview(c: Collector, v: unknown, draft: boolean) {
  if (v === null || v === undefined) {
    if (!draft) c.add('review', '검수 기록이 없어요. 사람이 기술 검수를 마친 판만 공개할 수 있어요(PRD AC-7).')
    return
  }
  if (!isObj(v)) {
    c.add('review', '검수 기록 객체 또는 null이어야 해요.')
    return
  }
  c.keys(v, KEYS.review, 'review')
  c.text(v, 'reviewer', 'review.')
  if (!isCalendarDate(v.reviewed_on)) c.add('review.reviewed_on', '달력에 있는 YYYY-MM-DD 날짜여야 해요.')
  c.textList(v.sources, 'review.sources')
  let url: URL | null = null
  try {
    url = typeof v.record_url === 'string' ? new URL(v.record_url) : null
  } catch {
    url = null
  }
  if (!url || url.protocol !== 'https:' || url.hostname === '' || url.pathname.length <= 1) {
    c.add('review.record_url', '검수 기록이 있는 페이지의 https 주소여야 해요(예: Linear 이슈 주소).')
  }
}

function checkSequence(c: Collector, v: unknown, stepCount: number) {
  if (v === undefined) return
  if (!isObj(v)) {
    c.add('sequence', '전체 흐름 객체여야 해요.')
    return
  }
  c.keys(v, KEYS.sequence, 'sequence')
  if (!oneOf(GUIDE_SEQUENCE_PLACEMENTS, v.placement)) {
    c.add('sequence.placement', `${GUIDE_SEQUENCE_PLACEMENTS.join(' 또는 ')}여야 해요.`)
  }
  const actors = new Set<string>()
  if (!Array.isArray(v.actors) || v.actors.length < 2) c.add('sequence.actors', '참여자가 둘 이상 있는 목록이어야 해요.')
  else
    v.actors.forEach((a, i) => {
      const p = `sequence.actors[${i}]`
      if (!isObj(a) || !isText(a.id) || !isText(a.name)) return c.add(p, '{ id, name } 형식이어야 해요.')
      if (actors.has(a.id)) c.add(`${p}.id`, `${show(a.id)} 참여자가 두 번 나와요.`)
      actors.add(a.id)
    })
  const tags = isObj(v.tags) ? v.tags : {}
  if (!isObj(v.tags) || Object.keys(v.tags).length === 0) c.add('sequence.tags', '선 모양 이름을 키로 쓰는 객체여야 해요.')
  else for (const [k, t] of Object.entries(v.tags)) if (!isText(t)) c.add(`sequence.tags.${k}`, '비어 있지 않은 글이어야 해요.')
  if (!Array.isArray(v.legend)) c.add('sequence.legend', '[선 모양 이름, 설명] 목록이어야 해요.')
  else
    v.legend.forEach((l, i) => {
      if (!Array.isArray(l) || l.length !== 2 || !hasKey(tags, l[0]) || !isText(l[1])) {
        c.add(`sequence.legend[${i}]`, '[tags에 있는 선 모양 이름, 설명] 형식이어야 해요.')
      }
    })
  if (v.note !== undefined && !isText(v.note)) c.add('sequence.note', '비어 있지 않은 글이어야 해요.')
  if (!Array.isArray(v.rows) || v.rows.length === 0) c.add('sequence.rows', '줄이 하나 이상 있는 목록이어야 해요.')
  else
    v.rows.forEach((r, i) => {
      const p = `sequence.rows[${i}]`
      if (!isObj(r)) return c.add(p, '줄 객체여야 해요.')
      if (!isInt(r.step) || (r.step as number) < 1 || (r.step as number) > stepCount) {
        c.add(`${p}.step`, `1부터 ${stepCount} 사이의 단계 번호여야 해요.`)
      }
      c.text(r, 'label', `${p}.`)
      if (r.k === 'msg') {
        for (const end of ['from', 'to'] as const) {
          if (!actors.has(r[end] as string)) c.add(`${p}.${end}`, `${show(r[end])} 참여자가 actors에 없어요.`)
        }
        if (r.from === r.to) c.add(p, '보내는 쪽과 받는 쪽이 같아요.')
        if (!hasKey(tags, r.prot)) c.add(`${p}.prot`, `${show(r.prot)} 선 모양이 tags에 없어요.`)
      } else if (r.k === 'note') {
        if (r.at !== 'both' && !actors.has(r.at as string)) c.add(`${p}.at`, `${show(r.at)} 참여자가 actors에 없어요('both'도 쓸 수 있어요).`)
      } else c.add(`${p}.k`, '"msg" 또는 "note"여야 해요.')
    })
  if (v.placement === 'appendix') {
    const a = v.appendix
    if (!isObj(a)) c.add('sequence.appendix', 'placement가 appendix면 부록 칸 내용이 있어야 해요.')
    else {
      c.text(a, 'short', 'sequence.appendix.')
      c.text(a, 'title', 'sequence.appendix.')
      c.textList(a.body, 'sequence.appendix.body')
      if (!isObj(a.callout) || !isText(a.callout.route) || !isText(a.callout.msg)) {
        c.add('sequence.appendix.callout', '{ route, msg } 형식이어야 해요.')
      }
    }
  } else if (v.appendix !== undefined) {
    c.add('sequence.appendix', 'placement가 last_step이면 부록 칸을 쓰지 않아요.')
  }
}

export function validateGuide(data: unknown, options: ValidateGuideOptions = {}): GuideIssue[] {
  const c = new Collector()
  if (!isObj(data)) {
    c.add('(파일)', '가이드 객체여야 해요.')
    return c.issues
  }
  const g = data
  c.keys(g, KEYS.guide, '')
  if (g.schema_version !== GUIDE_SCHEMA_VERSION) c.add('schema_version', `${GUIDE_SCHEMA_VERSION}이어야 해요.`)
  if (typeof g.slug !== 'string' || !SLUG_RE.test(g.slug)) c.add('slug', '소문자·숫자·하이픈만 쓴 이름이어야 해요(예: tcp-connection).')
  else if (options.fileSlug !== undefined && g.slug !== options.fileSlug) {
    c.add('slug', `파일 이름(${options.fileSlug}.json)과 같아야 해요.`)
  }
  for (const k of ['title', 'scene', 'note'] as const) c.text(g, k, '')
  for (const k of ['term_key', 'note_id'] as const) {
    if (g[k] !== null && !isText(g[k])) c.add(k, '비어 있지 않은 글 또는 null이어야 해요.')
  }
  if (!isInt(g.revision) || (g.revision as number) < 1) c.add('revision', '1 이상의 정수여야 해요.')
  checkReview(c, g.review, options.draft === true)
  if (g.end_text !== undefined && !isText(g.end_text)) c.add('end_text', '비어 있지 않은 글이어야 해요.')

  // 지도
  let ids = new Set<string>()
  if (!isObj(g.map)) c.add('map', '지도 객체여야 해요.')
  else {
    c.keys(g.map, KEYS.map, 'map')
    c.view(g.map.view, 'map.view')
    ids = checkNodes(c, g.map.nodes, 'map.nodes', false)
    const hasView = g.map.view_mobile !== undefined
    const hasNodes = g.map.nodes_mobile !== undefined
    if (hasView !== hasNodes) c.add('map', 'view_mobile과 nodes_mobile은 함께 있거나 함께 없어야 해요.')
    if (hasView) c.view(g.map.view_mobile, 'map.view_mobile')
    if (hasNodes) {
      const mobile = checkNodes(c, g.map.nodes_mobile, 'map.nodes_mobile', false)
      const same = mobile.size === ids.size && [...ids].every((id) => mobile.has(id))
      if (!same) c.add('map.nodes_mobile', '노드 id가 map.nodes와 같아야 해요.')
    }
  }

  const figureNames = checkFigures(c, g.figures)
  const usedFigures = new Set<string>()

  // 단계
  const steps = Array.isArray(g.steps) ? g.steps : []
  if (!Array.isArray(g.steps) || g.steps.length === 0) c.add('steps', '단계가 하나 이상 있는 목록이어야 해요.')
  steps.forEach((s, i) => {
    const p = `steps[${i}]`
    if (!isObj(s)) return c.add(p, '단계 객체여야 해요.')
    c.keys(s, KEYS.step, p)
    c.text(s, 'short', `${p}.`)
    c.text(s, 'title', `${p}.`)
    if (!oneOf(GUIDE_STEP_KINDS, s.kind)) c.add(`${p}.kind`, `${GUIDE_STEP_KINDS.join(', ')} 가운데 하나여야 해요.`)
    c.textList(s.body, `${p}.body`)
    // 모든 단계에 「무엇이 바뀌었나」가 있어야 한다(PRD AC-1).
    c.textList(s.changed, `${p}.changed`)
    if (!Array.isArray(s.active)) c.add(`${p}.active`, '노드 id 목록이어야 해요.')
    else
      s.active.forEach((id, j) => {
        if (!ids.has(id as string)) c.add(`${p}.active[${j}]`, `${show(id)} 노드가 지도에 없어요.`)
      })
    const arrows = Array.isArray(s.arrows) ? s.arrows : []
    if (!Array.isArray(s.arrows)) c.add(`${p}.arrows`, '목록이어야 해요(오가는 것이 없으면 []).')
    arrows.forEach((a, j) => {
      const q = `${p}.arrows[${j}]`
      if (!isObj(a)) return c.add(q, '화살표 객체여야 해요.')
      c.keys(a, KEYS.arrow, q)
      for (const end of ['from', 'to'] as const) {
        if (!ids.has(a[end] as string)) c.add(`${q}.${end}`, `${show(a[end])} 노드가 지도에 없어요.`)
      }
      // 따라가기 상자의 「무엇을」에 들어가는 글이다(PRD AC-5).
      if (!isText(a.label)) c.add(`${q}.label`, '무엇이 오가는지 적은 글이 있어야 해요.')
      if (a.local !== undefined && typeof a.local !== 'boolean') c.add(`${q}.local`, 'true 또는 false여야 해요.')
      if (a.style !== undefined && !oneOf(GUIDE_ARROW_STYLES, a.style)) c.add(`${q}.style`, `${GUIDE_ARROW_STYLES.join(' 또는 ')}여야 해요.`)
      if (a.shift !== undefined && !isNum(a.shift)) c.add(`${q}.shift`, '숫자여야 해요.')
      if (a.local !== true && a.from === a.to) c.add(q, '보내는 쪽과 받는 쪽이 같아요. 같은 노드 안의 확인이면 local: true를 붙여요.')
    })
    checkNodeKeys(c, s.notes, `${p}.notes`, ids, true)
    checkNodeKeys(c, s.roles, `${p}.roles`, ids, false)
    // 지도를 못 그려도 글로 같은 내용을 읽을 수 있어야 한다(PRD AC-5):
    // 오가는 것이 없는 단계라면 노드 상태 표시라도 있어야 따라가기 상자가 비지 않는다.
    if (arrows.length === 0 && isObj(s.notes) && Object.keys(s.notes).length === 0) {
      c.add(p, '오가는 메시지(arrows)도 노드 상태(notes)도 없어서 따라가기 상자가 비어요.')
    }
    if (s.aside !== undefined) {
      if (!isObj(s.aside) || !isText(s.aside.title) || !isText(s.aside.body)) c.add(`${p}.aside`, '{ title, body } 형식이어야 해요.')
    }
    if (s.figure !== undefined) {
      if (typeof s.figure !== 'string' || !figureNames.has(s.figure)) c.add(`${p}.figure`, `${show(s.figure)} 그림이 figures에 없어요.`)
      else usedFigures.add(s.figure)
    }
  })
  for (const name of figureNames) {
    if (!usedFigures.has(name)) c.add(`figures.${name}`, '어느 단계도 쓰지 않는 그림이에요.')
  }

  checkSequence(c, g.sequence, steps.length)
  return c.issues
}

// 화면 코드가 쓰는 타입 가드. 공개 기준 검사를 통과해야만 GuideFile로 본다.
export function isGuideFile(data: unknown): data is GuideFile {
  return validateGuide(data).length === 0
}

// 목록 파일 검사. guides는 slug → 그 가이드 파일 내용(검사를 통과했는지와 관계없이 읽은 값).
// 목록에 오른 가이드는 이 함수 안에서도 공개 기준 검사를 다시 거친다.
export function validateIndex(data: unknown, guides: ReadonlyMap<string, unknown>): GuideIssue[] {
  const c = new Collector()
  if (!Array.isArray(data)) {
    c.add('(목록)', '공개한 가이드 목록(배열)이어야 해요. 공개한 가이드가 없으면 []예요.')
    return c.issues
  }
  const seen = new Set<string>()
  data.forEach((e, i) => {
    const p = `[${i}]`
    if (!isObj(e)) return c.add(p, '목록 항목 객체여야 해요.')
    for (const k of ['slug', 'title', 'note_id', 'term_key'] as const) c.text(e, k, `${p}.`)
    if (!isText(e.slug)) return
    if (seen.has(e.slug)) c.add(`${p}.slug`, `${show(e.slug)}가 두 번 나와요.`)
    seen.add(e.slug)
    const g = guides.get(e.slug)
    if (!isObj(g)) return c.add(`${p}.slug`, `${e.slug}.json 가이드 파일이 없어요.`)
    for (const k of ['title', 'note_id', 'term_key'] as const) {
      if (e[k] !== g[k]) c.add(`${p}.${k}`, `가이드 파일의 값(${show(g[k])})과 달라요.`)
    }
    // 공개 목록에는 검수를 마친 판만 올린다(PRD AC-7·AC-9).
    if (!isObj(g.review)) c.add(p, `${e.slug}.json에 검수 기록(review)이 없어서 공개할 수 없어요.`)
    else if (!isGuideFile(g)) c.add(p, `${e.slug}.json이 공개 기준 검사를 통과하지 못해서 공개할 수 없어요.`)
  })
  return c.issues
}
