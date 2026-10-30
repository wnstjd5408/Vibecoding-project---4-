// F4-3a 계정 발급 폼 / F4-3b 발급 결과(MEG-68). 운영자가 이메일·표시 이름·초기 비밀번호로 일반 사용자 계정을 만든다.
// 초기 비밀번호는 입력만 받고 서버로 보낸 뒤에는 상태에도 화면에도 남기지 않는다(전달 방식은 사람이 정한 뒤 넣는다).
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Button, TextField } from '../../components/index.ts'
import { useOperatorApi } from '../useOperatorApi.ts'
import { classifyIssueFailure, issueAccount } from './accountsApi.ts'
import type { FieldReasons } from './accountsApi.ts'
import styles from './Accounts.module.css'

// 화면 문구. 오류 안내는 목업에 화면이 없어 모두 임시 문구다(문구 미정, 확정되면 이 한 곳만 고친다).
const MESSAGES = {
  emailExists: '이미 발급된 이메일이에요. 다른 이메일을 입력해 주세요.',
  failed: '계정을 발급하지 못했어요. 잠시 뒤에 다시 시도해 주세요.',
  // 서버가 알려 준 fields[].reason별 안내. 어느 칸인지는 오류가 붙는 입력 칸이 말해 준다.
  reasons: {
    required: '입력해 주세요.',
    too_long: '너무 길어요.',
    invalid_format: '형식이 맞지 않아요.',
    out_of_range: '길이가 맞지 않아요. 8자 이상 입력해 주세요.',
    invalid_value: '사용할 수 없는 값이에요.',
  } as Record<string, string>,
  reasonFallback: '값을 확인해 주세요.',
} as const

type Issued = { email: string; displayName: string }

export default function AccountsPage() {
  const operatorFetch = useOperatorApi()
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [issued, setIssued] = useState<Issued | null>(null)
  const [emailError, setEmailError] = useState('')
  const [fieldReasons, setFieldReasons] = useState<FieldReasons>({})
  const [formError, setFormError] = useState('')
  const resultRef = useRef<HTMLHeadingElement>(null)

  // 결과가 나타나면 스크린 리더가 바로 알도록 결과 제목으로 포커스를 옮긴다.
  useEffect(() => {
    if (issued) resultRef.current?.focus()
  }, [issued])

  const reasonText = (reason: string | undefined) => (reason ? (MESSAGES.reasons[reason] ?? MESSAGES.reasonFallback) : '')

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    // Enter 키로 다시 제출돼도 한 번에 한 요청만 보낸다.
    if (busy) return
    setBusy(true)
    setEmailError('')
    setFieldReasons({})
    setFormError('')
    const input = { email: email.trim(), displayName: displayName.trim(), password }
    try {
      await issueAccount(operatorFetch, input)
      // 성공하면 비밀번호를 포함해 입력을 모두 비우고, 결과에는 이메일·이름만 남긴다.
      setIssued({ email: input.email, displayName: input.displayName })
      setEmail('')
      setDisplayName('')
      setPassword('')
    } catch (error) {
      // 입력은 그대로 둬 고쳐서 다시 보낼 수 있게 한다. 권한 상실(401·403)은 useOperatorApi가 이미 처리해 화면이 곧 내보내진다.
      const failure = classifyIssueFailure(error)
      if (failure.kind === 'email_exists') setEmailError(MESSAGES.emailExists)
      else if (failure.kind === 'invalid') setFieldReasons(failure.fields)
      else setFormError(MESSAGES.failed)
    }
    setBusy(false)
  }

  return (
    <main>
      <h1 className={styles.title}>계정 발급</h1>
      <p className={styles.lead}>일반 사용자 계정을 만들어요. 가입 화면은 없어서 계정은 운영자만 발급해요.</p>
      {issued ? (
        <section className={styles.card} aria-labelledby="issued-title">
          <h2 id="issued-title" ref={resultRef} tabIndex={-1} className={styles.cardTitle}>
            계정을 발급했어요
          </h2>
          <dl className={styles.details}>
            <dt>이메일</dt>
            <dd>{issued.email}</dd>
            <dt>표시 이름</dt>
            <dd>{issued.displayName}</dd>
            <dt>역할</dt>
            <dd>일반 사용자</dd>
          </dl>
          <p className={styles.hint}>안내: 비밀번호는 화면에 다시 보여 주지 않아요.</p>
          <div>
            <Button onClick={() => setIssued(null)}>다른 계정 발급하기</Button>
          </div>
        </section>
      ) : (
        <form className={styles.card} onSubmit={handleSubmit}>
          <TextField
            label="이메일"
            name="email"
            type="email"
            autoComplete="off"
            placeholder="member@example.test"
            required
            value={email}
            error={emailError || reasonText(fieldReasons.email)}
            onChange={(event) => setEmail(event.target.value)}
          />
          <TextField
            label="표시 이름"
            name="display_name"
            autoComplete="off"
            placeholder="합성 사용자"
            required
            maxLength={80}
            value={displayName}
            error={reasonText(fieldReasons.displayName)}
            onChange={(event) => setDisplayName(event.target.value)}
          />
          <TextField
            label="초기 비밀번호"
            name="password"
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            hint="발급한 뒤에는 이 비밀번호를 다시 볼 수 없어요."
            value={password}
            error={reasonText(fieldReasons.password)}
            onChange={(event) => setPassword(event.target.value)}
          />
          <p className={styles.hint}>발급한 계정은 일반 사용자예요. 운영자 계정은 이 화면에서 만들 수 없어요.</p>
          {formError ? (
            <p role="alert" className={styles.error}>
              오류: {formError}
            </p>
          ) : null}
          <div>
            <Button type="submit" variant="primary" aria-disabled={busy ? 'true' : undefined}>
              발급하기
            </Button>
          </div>
        </form>
      )}
    </main>
  )
}
