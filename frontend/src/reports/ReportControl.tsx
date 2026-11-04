import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { isApiError } from '../api/client.ts'
import type { ReportTarget } from '../api/types.ts'
import { BottomSheet } from '../components/BottomSheet.tsx'
import { Button } from '../components/Button.tsx'
import { TextField } from '../components/TextField.tsx'
import { currentSession } from '../auth/sessionGeneration.ts'
import { useLoginPrompt } from '../loginPrompt/useLoginPrompt.ts'
import { classifyReportError, clampBody, countChars, REPORT_BODY_LIMIT, sendReport } from './report.ts'
import type { ReportFailure } from './report.ts'
import styles from './ReportControl.module.css'

// 화면 문구. 접수·기존 신고·404 문구는 승인된 문구이고 나머지는 목업에 없는 임시 문구다(문구 미정, 확정되면 이 한 곳만 고친다).
const MESSAGES = {
  open: '오류 신고',
  title: '오류 신고',
  field: '신고 내용',
  fieldHint: (count: number) => `${count.toLocaleString('en-US')} / ${REPORT_BODY_LIMIT.toLocaleString('en-US')}자`,
  submit: '신고 보내기',
  accepted: '신고가 접수됐어요',
  alreadyReported: '이미 접수된 신고예요',
  notFound: '신고할 대상을 찾을 수 없어요',
  bodyTooLong: `내용은 ${REPORT_BODY_LIMIT.toLocaleString('en-US')}자 이하로 써 주세요`,
  bodyInvalid: '내용을 확인한 뒤 다시 보내 주세요',
  rateLimited: '요청이 많아요. 잠시 뒤에 다시 보내 주세요.',
  waitBefore: (seconds: number) => `요청이 많아요. ${seconds}초 뒤에 다시 보낼 수 있어요`,
  failed: '신고를 보내지 못했어요. 다시 시도해 주세요.',
}

// 입력 칸 아래에 붙는 오류(422 body)와 입력 화면 위쪽의 일반 오류를 나눈다.
const FIELD_FAILURES: ReadonlySet<ReportFailure> = new Set(['body_too_long', 'body_invalid'])

type ReportControlProps = {
  // 신고 대상. AI 설명은 explanation.id, 퀴즈는 문항 id다.
  target: ReportTarget
}

// 오류 신고 버튼과 입력 화면(F2-3·F3-6). AI 설명 시트와 퀴즈 카드가 같이 쓴다.
// 입력 화면은 기존 BottomSheet를 그대로 쓴다. 오류가 나거나 로그인 안내를 열었다 닫아도 쓰던 내용은 남는다.
export function ReportControl({ target }: ReportControlProps) {
  const { handleLoginRequired } = useLoginPrompt()
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [failure, setFailure] = useState<{ kind: ReportFailure; seconds: number } | null>(null)
  const [waitingUntil, setWaitingUntil] = useState<number | null>(null)
  const [notice, setNotice] = useState('')
  // 이 컨트롤이 화면에 있는 동안만 응답을 쓴다. 시트·카드가 사라진 뒤 늦게 도착한 응답이 다른 화면에 영향을 주지 않게 한다.
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  // 같은 틱에 두 번 눌려도 한 번만 보내도록 상태가 아니라 ref로 막는다.
  const busy = useRef(false)

  // 서버가 정한 대기 시간이 끝날 때까지 보내기 버튼을 막는다(null이면 막지 않는다).
  useEffect(() => {
    if (waitingUntil === null) return
    // setTimeout은 약 24일(2^31-1ms)을 넘으면 바로 실행되므로 그 안으로 줄인다.
    const timer = setTimeout(() => setWaitingUntil(null), Math.min(Math.max(0, waitingUntil - Date.now()), 2_147_483_647))
    return () => clearTimeout(timer)
  }, [waitingUntil])

  // 로그인·로그아웃이 있었으면 이전 세션의 입력·대기·안내를 이어받지 않는다. 렌더 중에 세션 번호 변화를 알아채 상태를 바꾸는 것이 React가 권하는 방식이다.
  const session = currentSession()
  const [seenSession, setSeenSession] = useState(session)
  if (seenSession !== session) {
    setSeenSession(session)
    setOpen(false)
    setDraft('')
    setSending(false)
    setFailure(null)
    setWaitingUntil(null)
    setNotice('')
  }

  // 지난 실패 안내는 지우지 않는다. 보내는 중에 시트를 닫아 늦게 온 실패(대기 포함)도 다시 열면 이유가 보인다. 다음에 보낼 때 지운다.
  const openSheet = () => {
    setNotice('')
    setOpen(true)
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (busy.current || waitingUntil !== null) return
    busy.current = true
    setSending(true)
    setFailure(null)
    // 요청을 시작한 세션의 번호. 응답이 올 때 번호가 달라졌으면 그 응답은 이전 세션의 것이라 쓰지 않는다.
    const startedIn = currentSession()
    sendReport(target, draft).then(
      ({ alreadyReported }) => {
        busy.current = false
        if (!alive.current || startedIn !== currentSession()) return
        setSending(false)
        setDraft('')
        setOpen(false)
        setNotice(alreadyReported ? `${MESSAGES.accepted}. ${MESSAGES.alreadyReported}` : MESSAGES.accepted)
      },
      (error: unknown) => {
        busy.current = false
        if (!alive.current || startedIn !== currentSession()) return
        setSending(false)
        // 401 login_required는 로그인 안내가 맡는다. 안내를 닫아도 입력 화면과 내용은 그대로다.
        if (handleLoginRequired(error)) return
        const seconds = isApiError(error) && error.retryAfterSeconds !== undefined && error.retryAfterSeconds > 0 ? error.retryAfterSeconds : 0
        if (seconds > 0) setWaitingUntil(Date.now() + seconds * 1000)
        setFailure({ kind: classifyReportError(error), seconds })
      },
    )
  }

  const blocked = sending || waitingUntil !== null
  const failureText = failure === null ? null : {
    not_found: MESSAGES.notFound,
    body_too_long: MESSAGES.bodyTooLong,
    body_invalid: MESSAGES.bodyInvalid,
    rate_limited: failure.seconds > 0 ? MESSAGES.waitBefore(failure.seconds) : MESSAGES.rateLimited,
    failed: MESSAGES.failed,
  }[failure.kind]

  return (
    <>
      <Button variant="report" onClick={openSheet}>{MESSAGES.open}</Button>
      <p role="status" className={styles.notice}>{notice}</p>
      <BottomSheet open={open} onClose={() => setOpen(false)} title={MESSAGES.title}>
        <form className={styles.form} onSubmit={submit}>
          <TextField
            multiline
            rows={5}
            label={MESSAGES.field}
            hint={MESSAGES.fieldHint(countChars(draft))}
            error={failure !== null && FIELD_FAILURES.has(failure.kind) ? failureText ?? undefined : undefined}
            aria-disabled={sending}
            value={draft}
            onChange={(event) => setDraft(clampBody(event.target.value))}
          />
          {failureText !== null && failure !== null && !FIELD_FAILURES.has(failure.kind)
            ? <p role="alert" className={styles.alert}>{failureText}</p>
            : null}
          <div className={styles.actions}>
            <Button variant="primary" type="submit" aria-disabled={blocked}>{MESSAGES.submit}</Button>
          </div>
        </form>
      </BottomSheet>
    </>
  )
}
