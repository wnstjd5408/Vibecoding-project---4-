import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import type { QuizItem } from '../api/types.ts'
import { isApiError } from '../api/client.ts'
import { currentSession } from '../auth/sessionGeneration.ts'
import { AiBadge, AiBox, Button, TextField } from '../components/index.ts'
import { useLoginPrompt } from '../loginPrompt/useLoginPrompt.ts'
import { actionError, actionKey, actionWait, generateFollowup, saveFollowupAnswer, submitAnswer } from './quizActions.ts'
import styles from './QuizInteraction.module.css'

function AnswerForm({ label, button, disabled, submit }: { label: string; button: string; disabled: boolean; submit: (answer: string) => void }) {
  const [answer, setAnswer] = useState('')
  const [invalid, setInvalid] = useState(false)
  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    if (disabled) return
    if (!answer.trim() || [...answer].length > 1000) { setInvalid(true); return }
    setInvalid(false)
    submit(answer)
  }
  return <form className={styles.form} onSubmit={onSubmit}>
    <TextField multiline label={label} value={answer} rows={3} aria-disabled={disabled}
      hint={`${[...answer].length}/1,000자`} error={invalid ? '답을 1~1,000자로 입력해 주세요.' : undefined}
      onChange={(event) => { setAnswer(event.target.value); setInvalid(false) }} />
    <div><Button type="submit" variant="primary" aria-disabled={disabled}>{button}</Button></div>
  </form>
}

export function QuizInteraction({ initial, session, reload }: { initial: QuizItem; session: number; reload: () => void }) {
  const [item, setItem] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [until, setUntil] = useState(0)
  const [limit, setLimit] = useState(false)
  const [saved, setSaved] = useState<Record<number, string>>({})
  const active = useRef(false)
  const lock = useRef(false)
  const { handleLoginRequired } = useLoginPrompt()
  useEffect(() => { active.current = true; return () => { active.current = false } }, [])
  useEffect(() => {
    if (!until) return
    const timer = setTimeout(() => setUntil(0), Math.max(0, until - Date.now()))
    return () => clearTimeout(timer)
  }, [until])
  const valid = () => active.current && currentSession() === session
  async function run<T>(action: string, request: () => Promise<T>, apply: (data: T) => void) {
    if (lock.current || until !== 0 || !valid()) return
    lock.current = true
    setBusy(true)
    setError(null)
    try {
      const data = await request()
      if (valid()) apply(data)
    } catch (cause) {
      if (!valid()) return
      if (handleLoginRequired(cause)) { setError('로그인한 뒤 퀴즈를 다시 불러와 주세요.'); return }
      setError(actionError(cause))
      setUntil(actionWait(actionKey(session, item.id, action)))
      if (isApiError(cause, 'ai_limit_reached') || isApiError(cause, 'conflict', 'followup_limit_reached')) setLimit(true)
    } finally {
      lock.current = false
      if (valid()) setBusy(false)
    }
  }
  const disabled = busy || until !== 0
  const followups = item.followups ?? []
  return <div className={styles.flow}>
    {item.answered ? <>
      <p className={styles.status}>답함</p>
      <div className={styles.text}><strong>내 답</strong><p>{item.your_answer}</p></div>
      <AiBox label="AI 생성 정답과 해설">
        <h3 className={styles.aiTitle}>정답과 해설</h3>
        <div className={styles.text}><strong>정답</strong><p>{item.correct_answer}</p><strong>해설</strong><p>{item.explanation}</p></div>
      </AiBox>
      {followups.map((followup) => <section key={followup.seq} className={styles.followup} aria-label={`꼬리 질문 ${followup.seq}/2`}>
        <div className={styles.followupHead}><AiBadge /><h3 className={styles.followupStep}>꼬리 질문 {followup.seq}/2</h3></div>
        <p className={styles.status}>채점하지 않아요.</p>
        <p className={styles.text}>{followup.question}</p>
        {followup.answered ? <><p role="status">답 저장됨</p>{saved[followup.seq] !== undefined ? <p className={styles.text}>{saved[followup.seq]}</p> : null}</>
          : <AnswerForm label={`꼬리 질문 ${followup.seq}에 대한 답`} button="답 저장" disabled={disabled}
            submit={(answer) => { void run(`followup-${followup.seq}`, () => saveFollowupAnswer(session, item.id, followup.seq, answer), (result) => {
              setSaved((value) => ({ ...value, [followup.seq]: answer }))
              setItem((value) => ({ ...value, can_request_followup: result.can_request_followup, followups: value.followups.map((f) => f.seq === result.seq ? { ...f, answered: result.answered } : f) }))
            }) }} />}
      </section>)}
      {item.can_request_followup && followups.length < 2 && !limit ? <div><Button aria-disabled={disabled} onClick={() => { void run('followup', () => generateFollowup(session, item.id), (result) => {
        setItem((value) => ({ ...value, can_request_followup: false, followups: [...value.followups.filter((f) => f.seq !== result.seq), { seq: result.seq, question: result.question, answered: false }].sort((a, b) => a.seq - b.seq) }))
      }) }}>꼬리 질문 받기</Button></div> : null}
      {followups.length >= 2 && followups.every((f) => f.answered) ? <p role="status">꼬리 질문 2개를 모두 마쳤어요.</p> : null}
      {!item.can_request_followup && followups.length < 2 && followups.every((f) => f.answered) ? <div>
        <p className={styles.status}>다른 요청에서 꼬리 질문을 만들고 있을 수 있어요.</p>
        <Button aria-disabled={disabled} onClick={reload}>진행 상태 다시 확인</Button>
      </div> : null}
    </> : <AnswerForm label="문항에 대한 답" button="답 제출" disabled={disabled}
      submit={(answer) => { void run('answer', () => submitAnswer(session, item.id, answer), (result) => setItem((value) => ({ ...value, ...result, answered: true }))) }} />}
    {busy ? <p role="status">처리 중이에요.</p> : null}
    {error ? <div><p role="alert" className={styles.error}>{error}</p><Button aria-disabled={busy} onClick={reload}>퀴즈 다시 불러오기</Button></div> : null}
    {until !== 0 ? <p role="status">서버가 안내한 대기 시간이 지나면 다시 시도할 수 있어요.</p> : null}
  </div>
}

