// F4-1 로그인 화면(MEG-64). 목업 v0.2의 F4-1을 디자인 시스템 컴포넌트로 만든다.
import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { AppHeader, Button, StateMessage, TextField } from '../components/index.ts'
import { useAuth } from '../auth/useAuth.ts'
import { classifyLoginFailure, confirmLogin, landingPath, login } from '../auth/login.ts'
import type { LoginFailure } from '../auth/login.ts'
import { userPaths } from '../routes/paths.ts'
import styles from './LoginPage.module.css'

// 화면 문구. 실패 안내는 목업에 화면이 없어 모두 임시 문구다(문구 미정, 디자인 확정 때 이 한 곳만 고친다).
const MESSAGES = {
  // 티켓(MEG-64 AC-2)이 정한 임시 문구. 계정 없음·비밀번호 오류·비활성 계정이 모두 이 문구다.
  credentials: '이메일 또는 비밀번호가 맞지 않아요.',
  // 티켓에 문구가 없는 경우의 임시 문구
  rateLimitedTitle: '시도가 너무 많아요',
  rateLimitedBody: '잠시 뒤에 다시 시도해 주세요.',
  unavailableTitle: '로그인하지 못했어요',
  unavailableBody: '잠시 뒤에 다시 시도해 주세요.',
  // 제출하는 동안 버튼 글자(임시)
  submitting: '로그인하는 중이에요',
} as const

export default function LoginPage() {
  const navigate = useNavigate()
  const { refresh } = useAuth()
  const passwordRef = useRef<HTMLInputElement>(null)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [failure, setFailure] = useState<LoginFailure | null>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    // Enter 키로 다시 제출돼도 한 번에 한 요청만 보낸다.
    if (submitting) return
    setSubmitting(true)
    setFailure(null)
    try {
      await login(email, password)
      // E03으로 로그인 상태를 갱신하고, 상태가 확인됐을 때만 이동한다. 이동한 화면이 처음부터 로그인 상태를 읽는다.
      const confirmed = await confirmLogin(refresh)
      if (!confirmed.ok) {
        // 로그인은 됐는데 상태를 확인하지 못했다(E03 실패·쿠키 미적용). 성공으로 보내지 않고 안내한다. 비밀번호는 남겨 다시 시도하기 쉽게 한다.
        setFailure({ kind: 'unavailable' })
        setSubmitting(false)
        return
      }
      navigate(landingPath(confirmed.role), { replace: true })
    } catch (error) {
      const next = classifyLoginFailure(error)
      setFailure(next)
      // 계정 정보가 틀렸을 때만 이메일은 남기고 비밀번호를 비운 뒤 비밀번호 칸으로 포커스를 옮긴다.
      // 서버·네트워크 문제일 때는 입력을 그대로 두어 한 번에 다시 시도할 수 있게 한다.
      if (next.kind === 'credentials') {
        setPassword('')
        passwordRef.current?.focus()
      }
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.page}>
      <AppHeader title="CS 학습 노트" />
      <main className={styles.main}>
        <h1 className={styles.title}>로그인</h1>
        <p className={styles.lead}>계정은 운영자가 만들어 줘요. 직접 가입하는 기능은 없어요.</p>
        <form className={styles.form} onSubmit={handleSubmit}>
          <TextField
            label="이메일"
            name="email"
            type="email"
            autoComplete="username"
            placeholder="name@example.com"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <TextField
            ref={passwordRef}
            label="비밀번호"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            error={failure?.kind === 'credentials' ? MESSAGES.credentials : undefined}
          />
          {failure?.kind === 'rate_limited' ? (
            <StateMessage kind="error" title={MESSAGES.rateLimitedTitle} description={MESSAGES.rateLimitedBody} />
          ) : null}
          {failure?.kind === 'unavailable' ? (
            <StateMessage kind="error" title={MESSAGES.unavailableTitle} description={MESSAGES.unavailableBody} />
          ) : null}
          <Button type="submit" variant="primary" aria-disabled={submitting ? 'true' : undefined}>
            {submitting ? MESSAGES.submitting : '로그인'}
          </Button>
        </form>
        <Link to={userPaths.noteList} className={styles.guest}>
          로그인 없이 노트 보기
        </Link>
      </main>
    </div>
  )
}
