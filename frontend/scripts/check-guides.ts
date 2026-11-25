// 가이드 파일 형식 검사 (MEG-286). npm run build 전에 돈다.
//
//   node scripts/check-guides.ts                 src/guides/content 의 모든 가이드와 index.json 검사
//   node scripts/check-guides.ts --self-test     src/guides/fixtures 의 맞는 예시·틀린 예시로 검사기 자체를 확인
//   node scripts/check-guides.ts <파일...>        지정한 가이드 파일만 검사(공개 기준)
//   node scripts/check-guides.ts --draft <파일...> 검수 전 초안 기준으로 검사(review가 비어도 통과)
//
// 파일 이름은 <slug>.json이어야 한다(파일 안의 slug와 같은지 검사한다).
//
// 문제가 하나라도 있으면 종료 코드 1로 끝난다.
import { readdirSync, readFileSync } from 'node:fs'
import { basename, dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { isGuideFile, validateGuide, validateIndex, type GuideIssue } from '../src/guides/validate.ts'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const contentDir = join(root, 'src', 'guides', 'content')
const fixturesDir = join(root, 'src', 'guides', 'fixtures')

const rel = (p: string) => relative(root, p).replaceAll('\\', '/')
const slugOf = (p: string) => basename(p, '.json')

function readJson(path: string): { ok: true; value: unknown } | { ok: false; message: string } {
  try {
    return { ok: true, value: JSON.parse(readFileSync(path, 'utf8')) }
  } catch (e) {
    return { ok: false, message: `JSON으로 읽을 수 없어요: ${(e as Error).message}` }
  }
}

function report(file: string, issues: GuideIssue[]): boolean {
  if (issues.length === 0) {
    console.log(`ok  ${rel(file)}`)
    return true
  }
  for (const i of issues) console.error(`✗  ${rel(file)}: ${i.path} — ${i.message}`)
  return false
}

function checkFile(path: string, draft: boolean): { pass: boolean; issues: GuideIssue[]; value: unknown } {
  const read = readJson(path)
  if (!read.ok) return { pass: false, issues: [{ path: '(파일)', message: read.message }], value: undefined }
  const issues = validateGuide(read.value, { fileSlug: slugOf(path), draft })
  return { pass: issues.length === 0, issues, value: read.value }
}

const jsonFiles = (dir: string) =>
  readdirSync(dir)
    .filter((f) => f.endsWith('.json'))
    .sort()
    .map((f) => join(dir, f))

function checkContent(): boolean {
  let pass = true
  const guides = new Map<string, unknown>()
  for (const file of jsonFiles(contentDir).filter((f) => basename(f) !== 'index.json')) {
    const r = checkFile(file, false)
    guides.set(slugOf(file), r.value)
    pass = report(file, r.issues) && pass
  }
  const indexPath = join(contentDir, 'index.json')
  const index = readJson(indexPath)
  const indexIssues = index.ok ? validateIndex(index.value, guides) : [{ path: '(파일)', message: index.message }]
  pass = report(indexPath, indexIssues) && pass
  return pass
}

// 틀린 예시마다 「나와야 하는 문제의 위치」를 적어 둔다. 검사기가 그 위치를 짚지 못하면 실패다.
function selfTest(): boolean {
  let pass = true
  const validFiles = jsonFiles(join(fixturesDir, 'valid'))
  for (const file of validFiles) {
    const r = checkFile(file, false)
    if (!report(file, r.issues)) pass = false
    // 화면 코드가 쓰는 타입 가드도 같은 판정을 내야 한다.
    else if (!isGuideFile(r.value)) {
      console.error(`✗  ${rel(file)}: isGuideFile이 false를 냈어요.`)
      pass = false
    }
  }
  const expect = readJson(join(fixturesDir, 'invalid', 'expect.json'))
  if (!expect.ok || typeof expect.value !== 'object' || expect.value === null) {
    console.error(`✗  fixtures/invalid/expect.json: ${expect.ok ? '객체여야 해요.' : expect.message}`)
    return false
  }
  const expected = expect.value as Record<string, { draft?: boolean; paths?: unknown }>
  const files = jsonFiles(join(fixturesDir, 'invalid')).filter((f) => basename(f) !== 'expect.json')
  // 예시가 비면 검사기를 하나도 확인하지 않은 채 통과하게 된다.
  if (validFiles.length === 0 || files.length === 0) {
    console.error('✗  fixtures: 맞는 예시와 틀린 예시가 하나 이상씩 있어야 해요.')
    pass = false
  }
  for (const name of Object.keys(expected)) {
    if (!files.some((f) => basename(f) === name)) {
      console.error(`✗  fixtures/invalid/expect.json: ${name} 파일이 없어요.`)
      pass = false
    }
  }
  for (const file of files) {
    const want = expected[basename(file)]
    if (!want || !Array.isArray(want.paths) || want.paths.length === 0) {
      console.error(`✗  ${rel(file)}: expect.json에 기대하는 문제 위치(paths)가 없어요.`)
      pass = false
      continue
    }
    const r = checkFile(file, want.draft === true)
    const missing = (want.paths as unknown[]).filter((p) => !r.issues.some((i) => i.path === p))
    if (r.pass || missing.length > 0) {
      console.error(`✗  ${rel(file)}: 기대한 문제를 찾지 못했어요(${missing.join(', ') || '문제 없음으로 통과함'}).`)
      pass = false
    } else {
      console.log(`ok  ${rel(file)} (기대대로 실패: ${r.issues.map((i) => i.path).join(', ')})`)
    }
  }
  return pass
}

const args = process.argv.slice(2)
const draft = args.includes('--draft')
const selfTestMode = args.includes('--self-test')
const files = args.filter((a) => !a.startsWith('--')).map((f) => resolve(f))
const unknown = args.filter((a) => a.startsWith('--') && a !== '--draft' && a !== '--self-test')
let pass: boolean
if (unknown.length > 0) {
  console.error(`✗  알 수 없는 옵션: ${unknown.join(', ')}`)
  pass = false
} else if (selfTestMode) pass = selfTest()
else if (files.length > 0) pass = files.map((f) => report(f, checkFile(f, draft).issues)).every(Boolean)
else if (draft) {
  console.error('✗  --draft로 검사할 파일을 적어 주세요.')
  pass = false
} else pass = checkContent()
// process.exit()는 파이프로 넘기는 출력을 자를 수 있어 종료 코드만 정한다.
process.exitCode = pass ? 0 : 1
