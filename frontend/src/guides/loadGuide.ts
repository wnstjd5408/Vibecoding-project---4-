// 가이드 파일 한 편을 불러온다 (MEG-288). 가이드 화면 묶음에만 들어간다(노트 화면 번들을 키우지 않는다).
import type { GuideFile } from './types.ts'
import { isGuideFile } from './validate.ts'

// 공개 가이드 파일만 읽는다. 검수 전 초안(fixtures/local)과 시험용 예시(fixtures)는 이 경로로 열리지 않는다.
const FILES = import.meta.glob<unknown>(['./content/*.json', '!./content/index.json'], { import: 'default' })

// 한 번 불러온 가이드는 다시 받지 않는다. 실패하면 기록을 지워 다시 시도할 수 있게 한다.
const loaded = new Map<string, GuideFile>()
const pending = new Map<string, Promise<GuideFile>>()

export class GuideLoadError extends Error {}

export function peekGuide(slug: string): GuideFile | undefined {
  return loaded.get(slug)
}

export function loadGuide(slug: string): Promise<GuideFile> {
  const done = loaded.get(slug)
  if (done) return Promise.resolve(done)
  const running = pending.get(slug)
  if (running) return running
  const read = FILES[`./content/${slug}.json`]
  const next = (read ? read() : Promise.reject(new GuideLoadError(`${slug}.json 가이드 파일이 없어요.`)))
    .then((data) => {
      // 빌드 전 검사를 통과한 파일이지만, 화면이 기대하는 모양인지 한 번 더 확인한다.
      if (!isGuideFile(data)) throw new GuideLoadError(`${slug}.json이 공개 기준 검사를 통과하지 못했어요.`)
      loaded.set(slug, data)
      return data
    })
    .finally(() => pending.delete(slug))
  pending.set(slug, next)
  return next
}
