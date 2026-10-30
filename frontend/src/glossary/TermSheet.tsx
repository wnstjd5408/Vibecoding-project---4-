import { useCallback, useEffect, useRef, useState } from 'react'
import { apiFetch, isApiError } from '../api/client.ts'
import type { FavoriteResponse, GlossaryResponse, TermViewResponse } from '../api/types.ts'
import { useAuth } from '../auth/useAuth.ts'
import { BottomSheet } from '../components/BottomSheet.tsx'
import { Badge } from '../components/Badge.tsx'
import { Button } from '../components/Button.tsx'
import { FavoriteToggle } from '../components/FavoriteToggle.tsx'
import { StateMessage } from '../components/StateMessage.tsx'
import { TermLink } from '../components/TermLink.tsx'
import { NoteBody } from '../notes/NoteBody.tsx'
import styles from './TermSheet.module.css'

// 화면 문구. 임시이며 확정되면 이 한 곳만 고친다(PR에 기록).
const MESSAGES = {
  badge: '사전',
  loading: '설명을 불러오는 중이에요',
  notFound: '설명을 찾을 수 없어요',
  failed: '설명을 불러오지 못했어요',
  rateLimited: '요청이 많아요. 잠시 뒤에 다시 시도해 주세요.',
  retry: '다시 시도',
  imageFailed: '이미지를 불러오지 못했어요',
  viewNotRecorded: '열람 기록을 저장하지 못했어요',
  favoriteOn: '즐겨찾기에 저장했어요',
  favoriteOff: '즐겨찾기를 해제했어요',
  favoriteFailed: '즐겨찾기를 저장하지 못했어요',
}

type TermSheetProps = {
  open: boolean
  onClose: () => void
  // 열 때마다 달라지는 값. 같은 용어를 다시 열어도 새로 불러오고 열람을 다시 기록한다.
  openId: number
  termId: number | null
  // 시트 제목으로 바로 보이는 용어 이름(노트 응답에 이미 있다)
  label: string
  // 즐겨찾기 요청이 실패했을 때 부른다. 로그인 안내를 열었으면(401 login_required) true를 돌려주고, 그러면 이 시트는 그 안에서 닫힌다.
  // false면 이 시트가 짧은 오류 안내를 보인다.
  onLoginRequired: (error: unknown) => boolean
}

// 사전 용어 설명 바텀시트(F1-3). 열 때 E06으로 설명·이미지를 받고, 성공하면 E07로 열람을 한 번 기록한다.
// 시트는 기존 BottomSheet를 그대로 쓴다. 제목 포커스, Esc·닫기·막 누르기, 연 요소로의 포커스 복귀는 BottomSheet가 맡는다.
export function TermSheet({ open, onClose, openId, termId, label, onLoginRequired }: TermSheetProps) {
  return (
    <BottomSheet open={open} onClose={onClose} badge={<Badge tone="dictionary">{MESSAGES.badge}</Badge>} title={<TermLink>{label}</TermLink>}>
      {open && termId !== null ? <TermSheetContent key={openId} termId={termId} onLoginRequired={onLoginRequired} /> : null}
    </BottomSheet>
  )
}

type Result = { key: number; data: GlossaryResponse } | { key: number; error: 'not_found' | 'rate_limited' | 'failed' }

type SeenImage = { id: number; alt: string }

// 지금까지 본 이미지에 이번 응답의 이미지를 더한다. 먼저 본 순서를 지키고, 이미 있는 id는 처음 값을 둔다.
function mergeSeen(previous: SeenImage[], images: { id: number; alt: string }[]): SeenImage[] {
  const known = new Set(previous.map((image) => image.id))
  const added = images.filter((image) => !known.has(image.id)).map(({ id, alt }) => ({ id, alt }))
  return added.length === 0 ? previous : [...previous, ...added]
}

// 설명 본문은 용어 표시·노트 이미지 없이 마크다운만 그린다.
const NO_SPANS: never[] = []
const NO_IMAGES = {}
const NO_BROKEN: ReadonlySet<string> = new Set()
function noop() {}

// 시트가 열려 있는 동안만 있는 내용. 열 때마다 새로 만들어져 이전 용어의 응답·기록 상태가 남지 않는다.
function TermSheetContent({ termId, onLoginRequired }: { termId: number; onLoginRequired: (error: unknown) => boolean }) {
  const auth = useAuth()
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<Result | null>(null)
  const [brokenImages, setBrokenImages] = useState<ReadonlySet<number>>(new Set())
  // 지금까지 응답에 나온 이미지(id·대체 글). 다시 받은 응답에서 이미지가 빠져도 자리를 잃지 않고 대체 글로 보이게 한다.
  const [seenImages, setSeenImages] = useState<SeenImage[]>([])
  // 열람 기록 결과: 아직(null), 기록됨(true), 기록 안 됨(false: 서버가 false를 줬거나 요청이 실패)
  const [recorded, setRecorded] = useState<boolean | null>(null)
  const viewSent = useRef(false)
  // 이 시트 내용이 아직 화면에 있는지. 시트가 닫히거나 다른 노트·화면으로 옮겨 내용이 사라지면 false가 된다.
  // 닫힌 뒤 늦게 도착한 즐겨찾기 응답이 새 시트나 현재 화면에 영향을 주지 않게 쓴다(서버 저장이 취소된다는 뜻은 아니다).
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  // 즐겨찾기: 응답을 받은 뒤에만 상태를 바꾼다(null이면 E06의 is_favorite를 쓴다). 요청 중에는 중복 요청을 막는다.
  const [favoriteSaved, setFavoriteSaved] = useState<boolean | null>(null)
  const [favoritePending, setFavoritePending] = useState(false)
  const [favoriteFailed, setFavoriteFailed] = useState(false)
  // 이미지마다 E06을 다시 부르는 것은 한 번뿐이다. 새 URL도 실패하거나 URL이 그대로면 대체 글로 둔다.
  const refreshedImages = useRef(new Set<number>())
  const refreshing = useRef<Promise<GlossaryResponse> | null>(null)
  const current = result?.key === attempt ? result : null
  const data = current && 'data' in current ? current.data : null

  useEffect(() => {
    const controller = new AbortController()
    apiFetch<GlossaryResponse>(`/api/glossary/${termId}`, { signal: controller.signal })
      .then((response) => {
        if (controller.signal.aborted) return
        setSeenImages((previous) => mergeSeen(previous, response.images))
        setResult({ key: attempt, data: response })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        const reason = isApiError(error, 'not_found') ? 'not_found' : isApiError(error, 'rate_limited') ? 'rate_limited' : 'failed'
        setResult({ key: attempt, error: reason })
      })
    return () => controller.abort()
  }, [termId, attempt])

  // E06이 처음 성공한 뒤 열람을 한 번만 기록한다. 이미지 때문에 E06을 다시 받아도 다시 보내지 않는다.
  // 방문자도 부른다(서버가 recorded: false로 답한다). 기록 실패는 설명을 가리지 않는다.
  useEffect(() => {
    if (!data || viewSent.current) return
    viewSent.current = true
    apiFetch<TermViewResponse>('/api/term-views', { method: 'POST', body: { term_id: termId } })
      .then((response) => setRecorded(response.recorded))
      .catch(() => setRecorded(false))
  }, [data, termId])

  const onImageError = useCallback((imageId: number, failedUrl: string) => {
    const fail = () => setBrokenImages((previous) => new Set(previous).add(imageId))
    if (refreshedImages.current.has(imageId)) return fail()
    refreshedImages.current.add(imageId)
    refreshing.current ??= apiFetch<GlossaryResponse>(`/api/glossary/${termId}`)
      .then((response) => {
        setSeenImages((previous) => mergeSeen(previous, response.images))
        setResult({ key: attempt, data: response })
        return response
      })
      .finally(() => { refreshing.current = null })
    // 다시 받은 URL이 방금 실패한 URL과 같으면 img의 src가 그대로라 다시 불러오지 않는다. 새 응답에 그 이미지가 없는 경우와 함께 실패로 닫는다.
    refreshing.current.then((response) => {
      const next = response.images.find((image) => image.id === imageId)
      if (!next || next.url === failedUrl) fail()
    }, fail)
  }, [termId, attempt])

  async function changeFavorite(next: boolean) {
    if (favoritePending) return
    setFavoritePending(true)
    setFavoriteFailed(false)
    try {
      const response = await apiFetch<FavoriteResponse>(`/api/favorites/${termId}`, { method: 'PUT', body: { favorited: next } })
      // 그 사이 시트가 닫혔거나 화면이 바뀌었으면 결과를 쓰지 않는다.
      if (alive.current) setFavoriteSaved(response.is_favorite)
    } catch (error) {
      if (!alive.current) return
      // 401 login_required는 로그인 안내가 맡는다. 눌림 상태는 바뀐 적이 없어 되돌릴 것도 없다. 그 밖의 오류는 여기서 안내한다.
      if (!onLoginRequired(error)) setFavoriteFailed(true)
    } finally {
      if (alive.current) setFavoritePending(false)
    }
  }

  if (!current) return <StateMessage kind="loading" title={MESSAGES.loading} />
  if ('error' in current) {
    if (current.error === 'not_found') return <StateMessage kind="empty" title={MESSAGES.notFound} />
    return (
      <StateMessage
        kind="error"
        title={current.error === 'rate_limited' ? MESSAGES.rateLimited : MESSAGES.failed}
        action={<Button onClick={() => setAttempt((value) => value + 1)}>{MESSAGES.retry}</Button>}
      />
    )
  }

  // 로그인 상태인데 기록되지 않았으면 짧게 알린다. 방문자의 recorded: false는 정상이라 아무것도 보이지 않는다.
  const showViewNotice = recorded === false && auth.status !== 'loading' && auth.role !== 'visitor'
  const imagesNow = new Map(current.data.images.map((image) => [image.id, image]))
  const favorite = favoriteSaved ?? current.data.is_favorite ?? false
  return (
    <>
      <NoteBody compact body={current.data.body_markdown} spans={NO_SPANS} images={NO_IMAGES} brokenImages={NO_BROKEN} onTerm={noop} onImageError={noop} />
      {mergeSeen(seenImages, current.data.images).map((seen) => {
        const image = imagesNow.get(seen.id)
        // 실패했거나, 다시 받은 응답에서 빠진 이미지는 자리를 지키고 대체 글로 보인다.
        return !image || brokenImages.has(seen.id)
          ? <p key={seen.id} className={styles.imageFallback} role="img" aria-label={seen.alt || MESSAGES.imageFailed}>{MESSAGES.imageFailed}{seen.alt ? ` (${seen.alt})` : ''}</p>
          : <img key={seen.id} className={styles.image} src={image.url} alt={image.alt} onError={() => onImageError(image.id, image.url)} />
      })}
      {showViewNotice ? <p className={styles.notice} role="status">{MESSAGES.viewNotRecorded}</p> : null}
      {favoriteFailed ? <p className={styles.notice} role="alert">{MESSAGES.favoriteFailed}</p> : null}
      <div className={styles.actions}>
        <FavoriteToggle pressed={favorite} aria-disabled={favoritePending} onPressedChange={changeFavorite} />
      </div>
      {/* 저장 결과를 스크린 리더에 알린다. 실패했을 때는 비워 두어 저장된 것처럼 읽히지 않는다. */}
      <p className={styles.srOnly} role="status">{favoriteSaved === null || favoriteFailed ? '' : favoriteSaved ? MESSAGES.favoriteOn : MESSAGES.favoriteOff}</p>
    </>
  )
}
