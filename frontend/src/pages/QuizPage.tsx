import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { AccountMenu } from '../account/AccountMenu.tsx'
import type { QuizItem } from '../api/types.ts'
import { useAuth } from '../auth/useAuth.ts'
import { AiBadge, AppHeader, Button, DifficultyChip, LinkButton, QuizCard, StateMessage } from '../components/index.ts'
import type { Difficulty } from '../components/index.ts'
import { LOGIN_PROMPT_MESSAGES } from '../loginPrompt/messages.ts'
import { useLoginPrompt } from '../loginPrompt/useLoginPrompt.ts'
import { classifyQuizError, pollDelayMs, quizRetryAvailableAt, requestQuizToday } from '../quiz/quizToday.ts'
import type { QuizFailure } from '../quiz/quizToday.ts'
import { userPaths } from '../routes/paths.ts'
import styles from './QuizPage.module.css'

// 화면 문구. 목업에 있는 것(제목·안내·빈 상태)은 목업 그대로이고 나머지는 임시다(문구 미정, 확정되면 이 한 곳만 고친다).
const MESSAGES = {
  title: '오늘의 퀴즈',
  subtitle: '어제 열어 본·즐겨찾기한 용어로 만들었어요.',
  loading: '오늘의 퀴즈를 불러오는 중이에요',
  generating: '퀴즈를 만드는 중이에요',
  generatingDescription: '잠시 뒤에 저절로 다시 확인해요.',
  noneTitle: '오늘 풀 퀴즈가 없어요',
  noneDescription: '노트에서 용어를 열어 보면 다음 날 퀴즈가 만들어져요.',
  notOpenTitle: '오늘의 퀴즈는 아침 8시 30분부터 볼 수 있어요',
  notOpenDescription: '시간이 지난 뒤 다시 확인해 주세요.',
  failedTitle: '오늘의 퀴즈를 만들지 못했어요',
  failedDescription: '오늘은 더 이상 만들 수 없어요. 노트를 읽고 내일 다시 와 주세요.',
  limitTitle: '지금은 AI 사용 한도가 차서 퀴즈를 만들 수 없어요',
  limitDescription: '잠시 뒤에 다시 확인해 주세요.',
  loginTitle: '오늘의 퀴즈는 로그인한 뒤에 볼 수 있어요',
  errors: {
    rate_limited: '요청이 많아요. 잠시 뒤에 다시 시도해 주세요.',
    ai_unavailable: '퀴즈를 만드는 중 AI에 문제가 생겼어요. 다시 시도해 주세요.',
    failed: '퀴즈를 불러오지 못했어요',
  } satisfies Record<QuizFailure, string>,
  waitBefore: (seconds: number) => `${seconds}초 뒤에 다시 시도할 수 있어요`,
  recheck: '다시 확인',
  retry: '다시 시도',
  toNotes: '노트 보러 가기',
  answered: '답함',
}

// 화면이 보이는 상태. 서버의 여섯 상태(HTTP 200)와 오류, 로그인 필요를 나눠 보인다.
type View =
  | { kind: 'ready'; items: QuizItem[] }
  | { kind: 'not_open' }
  | { kind: 'none' }
  | { kind: 'generating' }
  | { kind: 'failed' }
  | { kind: 'ai_limit_reached' }
  | { kind: 'login' }
  | { kind: 'error'; reason: QuizFailure; until: number | null; seconds: number }

// 서버가 약속한 여섯 상태가 아니거나 ready인데 문항 목록이 배열이 아니면 화면을 깨지 않고 불러오지 못한 것으로 안내한다.
const FINAL_STATES = ['not_open', 'none', 'failed', 'ai_limit_reached'] as const
const BAD_RESPONSE: View = { kind: 'error', reason: 'failed', until: null, seconds: 0 }

function isItem(value: unknown): value is QuizItem {
  return typeof value === 'object' && value !== null && typeof (value as QuizItem).id === 'number' && typeof (value as QuizItem).question === 'string'
}

function toView(data: unknown): View {
  const response = (typeof data === 'object' && data !== null ? data : {}) as { status?: unknown; items?: unknown }
  if (response.status === 'ready' && Array.isArray(response.items)) {
    const items = response.items.filter(isItem)
    // 문항이 왔는데 하나도 읽을 수 없으면 비어 있는 것이 아니라 잘못된 응답이다.
    return items.length === 0 && response.items.length > 0 ? BAD_RESPONSE : { kind: 'ready', items }
  }
  const final = FINAL_STATES.find((state) => state === response.status)
  return final ? { kind: final } : BAD_RESPONSE
}

const LEVEL: Record<string, Difficulty> = { 하: 'low', 중: 'mid', 상: 'high' }

export default function QuizPage() {
  const auth = useAuth()
  const { handleLoginRequired, openLoginPrompt } = useLoginPrompt()
  // attempt: 사용자가 "다시 확인"·"다시 시도"를 누른 횟수, poll: generating이라 자동으로 다시 부른 횟수
  const [attempt, setAttempt] = useState(0)
  const [poll, setPoll] = useState(0)
  const [result, setResult] = useState<{ key: number; view: View } | null>(null)
  // 서버가 정한 대기 시간이 끝날 때까지 다시 시도 버튼을 막는다(null이면 막지 않는다).
  const [waitingUntil, setWaitingUntil] = useState<number | null>(null)
  const visitor = auth.status !== 'loading' && auth.role === 'visitor'
  const canRequest = auth.status !== 'loading' && !visitor
  const current = result?.key === attempt ? result.view : null
  // 계정이 바뀌면 이전 계정의 진행 중 요청·429 대기를 이어받지 않는다.
  const account = `${auth.role}:${auth.displayName ?? ''}`
  // 다시 확인·다시 시도를 누르면 눌린 버튼이 사라지므로, 결과 영역을 포커스 자리로 잡아 둔다.
  const bodyRef = useRef<HTMLDivElement>(null)

  // 방문자는 E11 요청 없이 공통 로그인 안내(퀴즈 문구)를 연다.
  useEffect(() => {
    if (visitor) openLoginPrompt({ body: LOGIN_PROMPT_MESSAGES.quizBody })
  }, [visitor, openLoginPrompt])

  useEffect(() => {
    if (!canRequest) return
    // 화면을 떠나거나 다시 확인을 눌러 이 요청이 낡았으면 응답을 쓰지 않고 예약한 재조회도 멈춘다.
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    requestQuizToday(account).then(
      (data: unknown) => {
        if (!alive) return
        const response = data as { status?: unknown; retry_after_seconds?: unknown } | null
        if (response?.status === 'generating') {
          // 다른 상태로 바뀌기 전까지만 서버가 준 간격으로 다시 부른다. 요청은 응답을 받은 뒤에만 예약해 겹치지 않는다.
          timer = setTimeout(() => setPoll((value) => value + 1), pollDelayMs(response.retry_after_seconds))
          setResult({ key: attempt, view: { kind: 'generating' } })
          return
        }
        setResult({ key: attempt, view: toView(data) })
      },
      (error: unknown) => {
        if (!alive) return
        // HTTP 401 + login_required만 공통 로그인 안내로 처리한다. 다른 오류는 아래의 오류별 안내다.
        if (handleLoginRequired(error, { body: LOGIN_PROMPT_MESSAGES.quizBody })) {
          setResult({ key: attempt, view: { kind: 'login' } })
          return
        }
        const until = quizRetryAvailableAt(account)
        setWaitingUntil(until)
        setResult({ key: attempt, view: { kind: 'error', reason: classifyQuizError(error), until, seconds: until === null ? 0 : Math.ceil((until - Date.now()) / 1000) } })
      },
    )
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [canRequest, attempt, poll, handleLoginRequired, account])

  useEffect(() => {
    if (waitingUntil === null) return
    // 일찍 풀려도 요청은 quizToday가 서버 기한까지 막는다.
    const timer = setTimeout(() => setWaitingUntil(null), Math.min(Math.max(0, waitingUntil - Date.now()), 2_147_483_647))
    return () => clearTimeout(timer)
  }, [waitingUntil])

  const recheck = () => {
    bodyRef.current?.focus({ preventScroll: true })
    setAttempt((value) => value + 1)
  }
  const toNotes = <Link className={styles.link} to={userPaths.noteList}>{MESSAGES.toNotes}</Link>

  let body
  if (auth.status === 'loading' || (canRequest && current === null)) {
    body = <StateMessage kind="loading" title={MESSAGES.loading} headingLevel={2} />
  } else if (visitor || current?.kind === 'login') {
    // 세션이 만료된 로그인 사용자가 안내를 닫아도 로그인으로 갈 길이 있게 한다(방문자는 헤더에 로그인 버튼이 있다).
    body = <StateMessage kind="empty" title={MESSAGES.loginTitle} headingLevel={2}
      action={<div className={styles.actions}>{current?.kind === 'login' ? <LinkButton to={userPaths.login}>로그인</LinkButton> : null}{toNotes}</div>} />
  } else if (current === null) {
    body = null
  } else if (current.kind === 'ready') {
    body = current.items.length === 0
      ? <StateMessage kind="empty" title={MESSAGES.noneTitle} description={MESSAGES.noneDescription} headingLevel={2} action={toNotes} />
      : <>
          <p className={styles.subtitle}>{MESSAGES.subtitle}</p>
          <ul className={styles.list}>
            {current.items.map((item) => <li key={item.id}>
              <QuizCard headingLevel={2} title={item.question}
                badges={<><AiBadge />{Object.hasOwn(LEVEL, item.difficulty) ? <DifficultyChip level={LEVEL[item.difficulty]} /> : null}</>}>
                {item.answered ? <p className={styles.answered}>{MESSAGES.answered}</p> : null}
              </QuizCard>
            </li>)}
          </ul>
          <div className={styles.footer}>{toNotes}</div>
        </>
  } else if (current.kind === 'generating') {
    body = <StateMessage kind="loading" title={MESSAGES.generating} description={MESSAGES.generatingDescription} headingLevel={2} />
  } else if (current.kind === 'error') {
    body = <StateMessage kind="error" headingLevel={2} title={MESSAGES.errors[current.reason]}
      description={waitingUntil !== null ? MESSAGES.waitBefore(current.seconds) : undefined}
      action={<Button aria-disabled={waitingUntil !== null} onClick={recheck}>{MESSAGES.retry}</Button>} />
  } else {
    const empty = {
      none: { title: MESSAGES.noneTitle, description: MESSAGES.noneDescription, recheck: true },
      not_open: { title: MESSAGES.notOpenTitle, description: MESSAGES.notOpenDescription, recheck: true },
      failed: { title: MESSAGES.failedTitle, description: MESSAGES.failedDescription, recheck: false },
      ai_limit_reached: { title: MESSAGES.limitTitle, description: MESSAGES.limitDescription, recheck: true },
    }[current.kind]
    body = <StateMessage kind="empty" headingLevel={2} title={empty.title} description={empty.description}
      action={<div className={styles.actions}>{empty.recheck ? <Button onClick={recheck}>{MESSAGES.recheck}</Button> : null}{toNotes}</div>} />
  }

  return <div className={styles.page}>
    <AppHeader title="CS 학습 노트" actions={
      auth.status === 'loading' ? null : visitor ? <LinkButton to={userPaths.login}>로그인</LinkButton> : <AccountMenu />
    } />
    <main className={styles.main} aria-busy={body !== null && (auth.status === 'loading' || (canRequest && current === null))}>
      <h1 className={styles.title}>{MESSAGES.title}</h1>
      <div ref={bodyRef} tabIndex={-1} className={styles.body}>{body}</div>
    </main>
  </div>
}
