// 개발 전용: 가이드 화면을 합성 예시로 확인하는 미리보기 (MEG-287). 제품 경로가 아니다.
// 제품 경로 /guides/:slug와 노트 연결·플래그는 MEG-288에서 붙인다.
//   /dev/guide?slug=sample-handshake   예시 고르기 (fixtures/valid, 그리고 저장소에 올리지 않는 fixtures/local)
//   &theme=dark                        어두운 테마
//   &failMap=1                         지도 그리기 실패(PRD AC-5 확인용)
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { GuidePage } from '../guides/GuidePage.tsx'
import type { GuideFile } from '../guides/types.ts'
import { validateGuide, type GuideIssue } from '../guides/validate.ts'

// 검수 전 초안을 로컬에서만 보려면 fixtures/local/<slug>.json에 둔다(.gitignore로 커밋하지 않는다).
const SOURCES = import.meta.glob<unknown>(['../guides/fixtures/valid/*.json', '../guides/fixtures/local/*.json'], { import: 'default' })
const slugOf = (path: string) => path.split('/').pop()!.replace(/\.json$/, '')

type Loaded = { state: 'loading' } | { state: 'ok'; guide: GuideFile } | { state: 'bad'; issues: GuideIssue[] } | { state: 'missing' }

export default function GuidePreviewPage() {
  const [query] = useSearchParams()
  const slugs = Object.keys(SOURCES).map(slugOf)
  const slug = query.get('slug') ?? slugs[0]
  const found = Object.keys(SOURCES).some((p) => slugOf(p) === slug)
  const [result, setResult] = useState<{ slug: string; loaded: Loaded } | null>(null)
  const loaded: Loaded = !found ? { state: 'missing' } : result?.slug === slug ? result.loaded : { state: 'loading' }

  useEffect(() => {
    const entry = Object.entries(SOURCES).find(([p]) => slugOf(p) === slug)
    if (!entry) return
    let alive = true
    void entry[1]().then((data) => {
      if (!alive) return
      // 미리보기는 검수 전 초안도 보여 준다(review 없음 허용). 공개 목록에는 오를 수 없다.
      const issues = validateGuide(data, { fileSlug: slug, draft: true })
      setResult({ slug, loaded: issues.length === 0 ? { state: 'ok', guide: data as GuideFile } : { state: 'bad', issues } })
    })
    return () => {
      alive = false
    }
  }, [slug])

  return (
    <div data-theme={query.get('theme') === 'dark' ? 'dark' : 'light'}>
      <nav aria-label="미리보기 예시" style={{ padding: '8px 16px', fontSize: 13, display: 'flex', gap: 12, flexWrap: 'wrap', background: 'var(--surface-100)', color: 'var(--ink)' }}>
        <strong>가이드 미리보기(개발 전용)</strong>
        {slugs.map((s) => (
          <a key={s} href={`?slug=${s}`} style={{ color: 'var(--ink)' }}>
            {s}
          </a>
        ))}
      </nav>
      {loaded.state === 'loading' && <p role="status">불러오는 중…</p>}
      {loaded.state === 'missing' && <p role="alert">「{slug}」 예시가 없어요.</p>}
      {loaded.state === 'bad' && (
        <ul role="alert">
          {loaded.issues.map((i, n) => (
            <li key={n}>
              {i.path} — {i.message}
            </li>
          ))}
        </ul>
      )}
      {loaded.state === 'ok' && <GuidePage key={slug} guide={loaded.guide} forceMapFailure={query.get('failMap') === '1'} />}
    </div>
  )
}
