// 공개한 가이드 목록과 기능 플래그 (MEG-288, PRD v0.5 5.2절).
// 목록 파일은 작아서 노트 화면 번들에 넣는다. 가이드 화면과 가이드 파일은 열 때만 불러온다(preloadGuide).
import indexData from './content/index.json'
import type { GuideIndexEntry } from './types.ts'

// 화면은 빌드 환경변수 VITE_GUIDES_ENABLED로 플래그를 안다. 백엔드 짝은 없다(프런트만 쓰는 기능).
// 1·true·yes·on(대소문자·앞뒤 공백 무시)만 켜짐이고, 그 밖은 모두 꺼짐이다(availability.ts의 위키 플래그와 같은 규칙).
// 꺼지면 노트의 가이드 연결과 /guides/* 경로가 모두 없다.
const ON_VALUES: ReadonlySet<string> = new Set(['1', 'true', 'yes', 'on'])

export function isGuidesOnValue(value: unknown): boolean {
  return ON_VALUES.has(String(value ?? '').trim().toLowerCase())
}

export const GUIDES_ENABLED: boolean = isGuidesOnValue(import.meta.env.VITE_GUIDES_ENABLED)

// 빌드 전 검사(npm run check:guides)가 목록 파일의 형식과 각 가이드의 공개 기준을 확인한다.
const INDEX: readonly GuideIndexEntry[] = indexData as GuideIndexEntry[]

// 공개 목록에 있는 가이드. 목록에 없으면 null이다(공개를 멈췄거나 지웠거나 없는 이름).
export function findGuide(slug: string): GuideIndexEntry | null {
  return INDEX.find((entry) => entry.slug === slug) ?? null
}

// 이 노트에 연결된 가이드. 노트 본문 첫머리에 연결을 그릴 때 쓴다(5.6절 2번).
export function guideForNote(noteId: number | string): GuideIndexEntry | null {
  return INDEX.find((entry) => entry.note_id === String(noteId)) ?? null
}

// 노트의 가이드 연결로 들어왔다는 표시(history state). 닫으면 브라우저 기록으로 돌아가 노트의 읽던 위치를 되살린다.
export type GuideEntryState = { from: 'note'; noteId: string }

// 노트에서 연결을 누르면 화면과 가이드 파일을 먼저 불러온 뒤에 이동한다.
// 불러오지 못하면 노트에 그대로 남아 오류와 다시 시도를 보인다(PRD AC-10).
export async function preloadGuide(slug: string): Promise<void> {
  const [, loader] = await Promise.all([import('../pages/GuideReadPage.tsx'), import('./loadGuide.ts')])
  await loader.loadGuide(slug)
}
