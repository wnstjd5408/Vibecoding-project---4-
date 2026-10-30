import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { isApiError } from '../api/client.ts'
import type { ExplainResponse } from '../api/types.ts'
import { AiBadge } from '../components/AiBadge.tsx'
import { AiBox } from '../components/AiBox.tsx'
import { Badge } from '../components/Badge.tsx'
import { BottomSheet } from '../components/BottomSheet.tsx'
import { Button } from '../components/Button.tsx'
import { StateMessage } from '../components/StateMessage.tsx'
import { NoteBody } from '../notes/NoteBody.tsx'
import { classifyExplainError, requestExplanation, retryAvailableAt } from './explain.ts'
import type { ExplainFailure, ExplainTarget } from './explain.ts'
import styles from './AiExplainSheet.module.css'

// 화면 문구. 목업에 없는 문구는 임시이며 확정되면 이 한 곳만 고친다(PR에 "문구 미정, 임시 문구"로 기록).
const MESSAGES = {
  aiPending: 'AI 생성·검수 전',
  aiGenerated: 'AI 생성',
  dictionary: '사전',
  loading: 'AI 설명을 만드는 중이에요',
  aiBoxLabel: 'AI 생성 설명',
  imageFailed: '이미지를 불러오지 못했어요',
  retry: '다시 시도',
  // 서버가 정한 대기 시간(retry_after_seconds)이 남았을 때
  waitBefore: (seconds: number) => `${seconds}초 뒤에 다시 시도할 수 있어요`,
  reloadNote: '노트 다시 불러오기',
  failures: {
    limit_reached: '오늘 쓸 수 있는 AI 설명을 모두 썼어요. 나중에 다시 시도해 주세요.',
    rate_limited: '요청이 많아요. 잠시 뒤에 다시 시도해 주세요.',
    ai_unavailable: 'AI가 설명을 만들지 못했어요. 다시 시도해 주세요.',
    in_progress: '같은 설명을 만드는 중이에요. 잠시 뒤에 다시 확인해 주세요.',
    stale_revision: '노트가 바뀌었어요. 노트를 다시 불러온 뒤 단어를 다시 골라 주세요.',
    result_unavailable: '이전 요청의 설명을 다시 가져올 수 없어요. 새로 요청해 주세요.',
    not_found: '설명할 수 없는 노트예요',
    invalid: '이 선택으로는 설명을 만들 수 없어요. 다른 단어를 골라 주세요.',
    failed: 'AI 설명을 불러오지 못했어요',
  } satisfies Record<ExplainFailure, string>,
}

// 다시 시도 버튼을 보이는 오류. 한도 소진·없는 노트·잘못된 선택은 다시 보내도 같은 결과라 버튼이 없다.
const RETRYABLE: ReadonlySet<ExplainFailure> = new Set(['rate_limited', 'ai_unavailable', 'in_progress', 'result_unavailable', 'failed'])

// 시트 제목으로 보이는 선택한 글. 길면 앞부분만 보인다(코드포인트 기준).
function shortTitle(text: string): string {
  const chars = [...text.trim()]
  return chars.length > 40 ? `${chars.slice(0, 40).join('')}…` : chars.join('')
}

// 검수 전 표시: pending이거나 review_status가 없는 설명(저장하지 않는 1회용 설명은 검수 상태가 없다)
function reviewPending(status: string | undefined): boolean {
  return status === undefined || status === 'pending'
}

const NO_SPANS: never[] = []
const NO_IMAGES = {}
const NO_BROKEN: ReadonlySet<string> = new Set()
function noop() {}

type AiExplainSheetProps = {
  open: boolean
  onClose: () => void
  // 열 때마다 달라지는 값. 같은 선택을 다시 열어도 새로 요청한다(진행 중인 요청이 있으면 그 요청을 이어서 본다).
  openId: number
  target: ExplainTarget | null
  // 시트 제목으로 바로 보이는 선택한 글
  text: string
  // 요청이 실패했을 때 부른다. 401 login_required라 로그인 안내를 열었으면 true를 돌려주고, 이 시트는 그 안에서 닫힌다.
  onLoginRequired: (error: unknown) => boolean
  // 노트가 바뀌었다(409 stale_revision)는 안내에서 "노트 다시 불러오기"를 눌렀을 때 부른다.
  onReloadNote: () => void
}

// AI 설명 시트(F2-2a). 열릴 때 E09를 한 번 부르고, 응답 세 갈래(AI 설명·사전 설명·1회용 설명)를 그린다.
// 시트는 기존 BottomSheet를 그대로 쓴다. 제목 포커스, Esc·닫기·막 누르기, 연 요소로의 포커스 복귀는 BottomSheet가 맡는다.
export function AiExplainSheet({ open, onClose, openId, target, text, onLoginRequired, onReloadNote }: AiExplainSheetProps) {
  // 제목 위 표시(목업 F2-2a). 응답이 오면 갈래에 따라 정해지고, 시트를 새로 열면 비운다. 렌더 중에 열림 번호 변화를 알아채 바꾸는 것이 React가 권하는 방식이다.
  const [badge, setBadge] = useState<ReactNode>(null)
  const [badgeFor, setBadgeFor] = useState(openId)
  if (badgeFor !== openId) {
    setBadgeFor(openId)
    setBadge(null)
  }
  return (
    <BottomSheet open={open} onClose={onClose} badge={badge} title={shortTitle(text)}>
      {open && target !== null ? <AiExplainContent key={openId} target={target} onBadge={setBadge} onLoginRequired={onLoginRequired} onReloadNote={onReloadNote} /> : null}
    </BottomSheet>
  )
}

// until: 서버가 정한 재시도 가능 시각(ms). 기다릴 필요가 없으면 null이다.
type Result = { key: number; data: ExplainResponse } | { key: number; failure: ExplainFailure; until: number | null; seconds: number }

function AiExplainContent({ target, onBadge, onLoginRequired, onReloadNote }: Pick<AiExplainSheetProps, 'onLoginRequired' | 'onReloadNote'> & { target: ExplainTarget; onBadge: (badge: ReactNode) => void }) {
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<Result | null>(null)
  const [brokenImages, setBrokenImages] = useState<ReadonlySet<number>>(new Set())
  // 이 내용이 화면에 있는 동안만 응답을 쓴다. 닫거나 화면을 옮긴 뒤 늦게 도착한 응답이 새 시트·현재 화면에 영향을 주지 않게 한다.
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  // 부모가 다시 그려져 콜백이 새로 만들어져도 요청을 다시 보내지 않도록 최신 콜백만 ref에 둔다.
  const callbacks = useRef({ onLoginRequired, onBadge })
  useEffect(() => {
    callbacks.current = { onLoginRequired, onBadge }
  })
  const current = result?.key === attempt ? result : null
  // 서버가 정한 대기 시간이 끝날 때까지 다시 시도 버튼을 막는다(null이면 막지 않는다).
  const [waitingUntil, setWaitingUntil] = useState<number | null>(null)
  useEffect(() => {
    if (waitingUntil === null) return
    // setTimeout은 약 24일(2^31-1ms)을 넘으면 바로 실행되므로 그 안으로 줄인다. 일찍 풀려도 요청은 explain.ts가 서버 기한까지 막는다.
    const timer = setTimeout(() => setWaitingUntil(null), Math.min(Math.max(0, waitingUntil - Date.now()), 2_147_483_647))
    return () => clearTimeout(timer)
  }, [waitingUntil])

  useEffect(() => {
    requestExplanation(target).then(
      (data) => {
        if (!alive.current) return
        callbacks.current.onBadge(data.source === 'glossary'
          ? <Badge tone="dictionary">{MESSAGES.dictionary}</Badge>
          : <AiBadge>{reviewPending(data.explanation.review_status) ? MESSAGES.aiPending : MESSAGES.aiGenerated}</AiBadge>)
        setResult({ key: attempt, data })
      },
      (error: unknown) => {
        if (!alive.current) return
        // 401 login_required는 로그인 안내가 맡는다(로그인 사용자의 세션 만료). 그 밖의 오류는 아래의 오류별 안내다.
        if (callbacks.current.onLoginRequired(error)) return
        const until = retryAvailableAt(target)
        setWaitingUntil(until)
        setResult({ key: attempt, failure: isApiError(error) ? classifyExplainError(error) : 'failed', until, seconds: until === null ? 0 : Math.ceil((until - Date.now()) / 1000) })
      },
    )
  }, [target, attempt])

  if (!current) return <StateMessage kind="loading" title={MESSAGES.loading} />
  if ('failure' in current) {
    const failure = current.failure
    return (
      <StateMessage
        kind="error"
        title={MESSAGES.failures[failure]}
        description={waitingUntil !== null && RETRYABLE.has(failure) ? MESSAGES.waitBefore(current.seconds) : undefined}
        action={failure === 'stale_revision'
          ? <Button onClick={onReloadNote}>{MESSAGES.reloadNote}</Button>
          : RETRYABLE.has(failure) ? <Button aria-disabled={waitingUntil !== null} onClick={() => setAttempt((value) => value + 1)}>{MESSAGES.retry}</Button> : undefined}
      />
    )
  }

  const data = current.data
  if (data.source === 'glossary') {
    // 사전에 있는 용어: 사전 설명과 이미지를 그대로 보인다. E06을 다시 부르지 않는다.
    return (
      <>
        <NoteBody compact body={data.body_markdown} spans={NO_SPANS} images={NO_IMAGES} brokenImages={NO_BROKEN} onTerm={noop} onImageError={noop} />
        {data.images.map((image) => brokenImages.has(image.id)
          ? <p key={image.id} className={styles.imageFallback} role="img" aria-label={image.alt || MESSAGES.imageFailed}>{MESSAGES.imageFailed}{image.alt ? ` (${image.alt})` : ''}</p>
          : <img key={image.id} className={styles.image} src={image.url} alt={image.alt} onError={() => setBrokenImages((previous) => new Set(previous).add(image.id))} />)}
      </>
    )
  }
  // AI 설명(저장된 공유 설명 또는 저장하지 않는 1회용 설명). AI 본문은 텍스트로만 보인다.
  return (
    <AiBox label={MESSAGES.aiBoxLabel}>
      <p className={styles.body}>{data.explanation.body}</p>
    </AiBox>
  )
}
