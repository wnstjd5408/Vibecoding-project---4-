// 내용 초안 생성기(비공개 Artifact용 build.mjs)의 레슨 객체를 가이드 파일 형식으로 바꾼다 (MEG-286).
//
//   node scripts/convert-guide.ts <레슨 모듈.mjs> <내보낸 이름> --slug <slug>
//        [--figures <FIGS를 내보내는 모듈.mjs>] [--term-key <사전 용어>] [--note-id <노트 id>] [--out <파일>]
//
// 결과의 review는 null이다. 사람이 기술 검수를 마친 뒤 review를 채워야 공개 목록에 올릴 수 있다.
// 검수 전 초안은 공개 저장소에 올리지 않는다(--out으로 src/guides 안을 주면 거절한다).
// --out 없이 실행하면 표준 출력으로 낸다. 검사하려면 파일 이름을 <slug>.json으로 저장한다.
import { writeFileSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import {
  GUIDE_SCHEMA_VERSION,
  type GuideFigurePanel,
  type GuideFile,
  type GuideSequence,
  type GuideSequenceRow,
  type GuideStep,
} from '../src/guides/types.ts'

type Loose = Record<string, unknown>

const guidesDir = join(resolve(dirname(fileURLToPath(import.meta.url)), '..'), 'src', 'guides')

function parseArgs(argv: string[]) {
  const [modulePath, exportName, ...rest] = argv
  const opts: Record<string, string> = {}
  for (let i = 0; i < rest.length; i += 2) {
    const key = rest[i]
    const value = rest[i + 1]
    if (!key?.startsWith('--') || value === undefined) throw new Error(`옵션 형식이 틀려요: ${key ?? ''}`)
    opts[key.slice(2)] = value
  }
  if (!modulePath || !exportName || !opts.slug) {
    throw new Error('사용법: node scripts/convert-guide.ts <레슨 모듈.mjs> <내보낸 이름> --slug <slug> [--figures <모듈>] [--term-key <용어>] [--note-id <id>] [--out <파일>]')
  }
  return { modulePath, exportName, opts }
}

const load = async (path: string) => (await import(pathToFileURL(resolve(path)).href)) as Loose

// 생성기의 기본값(참여자 둘: 브라우저·서버, TLS 보호 수준 세 가지)을 그대로 옮긴다.
const DEFAULT_ACTORS = [
  { id: 'b', name: '브라우저' },
  { id: 's', name: '서버' },
]
const DEFAULT_TAGS = { plain: '평문', hs: '연결 준비용 키로 암호화', app: '세션 키로 암호화' }
const DEFAULT_LEGEND: [string, string][] = [
  ['plain', '평문'],
  ['hs', '연결 준비용 키'],
  ['app', '세션 키'],
]
const OTHER: Record<string, string> = { b: 's', s: 'b' }

// undefined인 키를 빼서 JSON이 깔끔하게 나오게 한다.
function compact<T extends object>(o: T): T {
  return Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined)) as T
}

function convertSteps(steps: Loose[]): GuideStep[] {
  return steps.map((s) =>
    compact({
      short: s.short,
      kind: s.kind,
      title: s.title,
      body: s.body,
      changed: s.changed,
      active: s.active ?? [],
      arrows: ((s.arrows as Loose[] | undefined) ?? []).map((a) =>
        // 생성기의 bad는 형식에서 risk(도착하지만 위험)와 lost(사라짐)로 나뉜다. 기본은 risk로 옮기고,
        // 사라지는 메시지는 사람이 lost로 고친다(2026-11-25 김준성 결정).
        compact({ from: a.from, to: a.to, label: a.label, local: a.local, style: a.style === 'bad' ? 'risk' : a.style, shift: a.shift }),
      ),
      notes: s.notes ?? {},
      roles: s.roles,
      aside: s.aside,
      figure: s.figure,
    }) as GuideStep,
  )
}

function convertSequence(lesson: Loose): GuideSequence | undefined {
  const rows = lesson.sequence as Loose[] | undefined
  if (!Array.isArray(rows)) return undefined
  const appendix = lesson.seqAppendix as Loose | undefined
  const converted: GuideSequenceRow[] = rows.map((r) =>
    r.k === 'msg'
      ? { k: 'msg', step: r.step as number, from: r.from as string, to: (r.to as string) ?? OTHER[r.from as string], label: r.label as string, prot: r.prot as string }
      : { k: 'note', step: r.step as number, at: r.at as string, label: r.label as string },
  )
  return compact({
    placement: appendix ? 'appendix' : 'last_step',
    actors: (lesson.seqActors as GuideSequence['actors'] | undefined) ?? DEFAULT_ACTORS,
    tags: (lesson.seqTags as Record<string, string> | undefined) ?? DEFAULT_TAGS,
    legend: (lesson.seqLegend as [string, string][] | undefined) ?? DEFAULT_LEGEND,
    note: lesson.seqNote as string | undefined,
    rows: converted,
    appendix: appendix
      ? {
          short: appendix.short as string,
          title: appendix.title as string,
          body: appendix.body as string[],
          callout: { route: (appendix.co as Loose).route as string, msg: (appendix.co as Loose).msg as string },
        }
      : undefined,
  }) as GuideSequence
}

async function main() {
  const { modulePath, exportName, opts } = parseArgs(process.argv.slice(2))
  // 변환 결과는 검수 전 초안이다. 공개 저장소의 가이드 폴더에 바로 쓰지 않는다.
  if (opts.out && resolve(opts.out).startsWith(guidesDir)) {
    throw new Error(`검수 전 초안은 ${relative(process.cwd(), guidesDir)} 안에 쓰지 않아요. 저장소 밖 경로를 --out으로 주세요.`)
  }
  const lesson = (await load(modulePath))[exportName] as Loose | undefined
  if (!lesson) throw new Error(`${modulePath}에 ${exportName} 내보내기가 없어요.`)
  if (!Array.isArray(lesson.steps) || !Array.isArray(lesson.nodes) || !Array.isArray(lesson.view)) {
    throw new Error(`${exportName}에 steps·nodes·view가 없어요. 생성기 레슨 객체인지 확인해 주세요.`)
  }
  const appendix = lesson.seqAppendix as Loose | undefined
  if (appendix && (typeof appendix.co !== 'object' || appendix.co === null)) {
    throw new Error(`${exportName}.seqAppendix에 따라가기 상자 글(co)이 없어요.`)
  }
  const steps = convertSteps(lesson.steps as Loose[])

  const figureNames = [...new Set(steps.map((s) => s.figure).filter((f): f is string => Boolean(f)))]
  const figures: Record<string, GuideFigurePanel[]> = {}
  if (figureNames.length > 0) {
    if (!opts.figures) throw new Error(`그림 ${figureNames.join(', ')}을 쓰므로 --figures 모듈이 필요해요.`)
    const all = (await load(opts.figures)).FIGS as Record<string, GuideFigurePanel[]> | undefined
    for (const name of figureNames) {
      if (!all?.[name]) throw new Error(`--figures 모듈에 ${name} 그림이 없어요.`)
      figures[name] = all[name]
    }
  }

  const guide: GuideFile = compact({
    schema_version: GUIDE_SCHEMA_VERSION,
    slug: opts.slug,
    title: lesson.title as string,
    scene: lesson.scene as string,
    note: lesson.note as string,
    term_key: opts['term-key'] ?? null,
    note_id: opts['note-id'] ?? null,
    revision: 1,
    review: null,
    end_text: lesson.endText as string | undefined,
    map: { view: lesson.view as [number, number], nodes: lesson.nodes as GuideFile['map']['nodes'] },
    steps,
    figures,
    sequence: convertSequence(lesson),
  })

  const json = JSON.stringify(guide, null, 2) + '\n'
  if (opts.out) {
    writeFileSync(resolve(opts.out), json)
    console.error(`썼어요: ${opts.out} (review는 null — 검수 뒤 채워요)`)
  } else process.stdout.write(json)
}

try {
  await main()
} catch (e) {
  console.error(`✗  ${(e as Error).message}`)
  process.exitCode = 1
}
