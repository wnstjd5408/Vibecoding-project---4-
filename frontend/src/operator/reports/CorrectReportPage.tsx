// F5-3 사전에 바른 설명 넣기(MEG-84). 신고된 AI 설명을 옆에 보면서 바른 설명을 사전으로 저장한다. 목업을 따른다.
// 저장해도 신고 상태는 바뀌지 않는다. 신고 목록에서 따로 처리됨으로 바꾼다.
import { useEffect, useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { isApiError } from '../../api/client.ts'
import { AiBox, Button, LinkButton, StateMessage, TextField } from '../../components/index.ts'
import { Badge } from '../../components/Badge.tsx'
import { operatorPaths } from '../../routes/paths.ts'
import { useOperatorGuard } from '../useOperatorGuard.ts'
import { IMAGE_REJECTED_MESSAGE, IMAGE_TYPES, isAllowedImage } from './imageRules.ts'
import { getReport, saveDictionaryEntry } from './reportsApi.ts'
import type { Report } from './reportsApi.ts'
import styles from './Reports.module.css'

// 화면 문구. 실패 안내는 목업에 화면이 없어 임시 문구다(문구 미정, 확정되면 이 한 곳만 고친다).
const MESSAGES = {
  required: '용어 이름과 바른 설명을 입력해 주세요.',
  saveFailed: '저장하지 못했어요. 잠시 뒤에 다시 시도해 주세요.',
  notice: '안내: 저장하면 이 용어는 사전 설명이 먼저 보이고 AI 설명은 무효가 돼요. 신고 상태는 신고 목록에서 따로 바꿔요.',
  saved: '사전 설명을 저장했어요.',
} as const

type Load = { key: string; report: Report } | { key: string; state: 'notFound' | 'failed' }

export default function CorrectReportPage() {
  const { reportId } = useParams()
  const { onApiError } = useOperatorGuard()
  const [attempt, setAttempt] = useState(0)
  const [load, setLoad] = useState<Load | null>(null)

  const key = `${reportId}:${attempt}`
  const current = load?.key === key ? load : null

  useEffect(() => {
    let live = true
    const loadKey = `${reportId}:${attempt}`
    getReport(Number(reportId)).then(
      (report) => live && setLoad({ key: loadKey, report }),
      (failure) => {
        if (!live || onApiError(failure)) return
        setLoad({ key: loadKey, state: isApiError(failure, 'not_found') ? 'notFound' : 'failed' })
      },
    )
    return () => {
      live = false
    }
  }, [reportId, attempt, onApiError])

  return (
    <main>
      <Link to={operatorPaths.reports} className={styles.link}>
        신고 목록으로
      </Link>
      <h1 className={styles.pageTitle}>사전에 바른 설명 넣기</h1>
      {!current ? (
        <StateMessage kind="loading" title="신고를 불러오는 중이에요" />
      ) : 'state' in current ? (
        current.state === 'notFound' ? (
          <StateMessage
            kind="empty"
            title="찾을 수 없는 신고예요"
            description="목록에서 다시 골라 주세요."
            action={<LinkButton to={operatorPaths.reports}>신고 목록으로</LinkButton>}
          />
        ) : (
          <StateMessage
            kind="error"
            title="신고를 불러오지 못했어요"
            description="잠시 뒤에 다시 시도해 주세요."
            action={<Button onClick={() => setAttempt((count) => count + 1)}>다시 시도</Button>}
          />
        )
      ) : current.report.kind !== '용어 설명' ? (
        // 문항 신고에는 사전 설명이 없다(목록에도 이 화면으로 오는 버튼이 없다).
        <StateMessage
          kind="empty"
          title="사전 설명을 넣을 수 없는 신고예요"
          description="용어 설명 신고에서만 바른 설명을 넣을 수 있어요."
          action={<LinkButton to={operatorPaths.reports}>신고 목록으로</LinkButton>}
        />
      ) : (
        <div className={styles.correctLayout}>
          <section className={styles.card} aria-label="신고된 AI 설명">
            <h2 className={styles.cardTitle}>신고된 AI 설명 · {current.report.title}</h2>
            <AiBox label="신고된 AI 생성 설명">
              <Badge tone="ai">AI 생성</Badge>
              <p className={styles.reportBody}>{current.report.body}</p>
            </AiBox>
          </section>
          <CorrectForm report={current.report} />
        </div>
      )}
    </main>
  )
}

type Upload = { file: File; url: string }

function CorrectForm({ report }: { report: Report }) {
  const navigate = useNavigate()
  const { onApiError } = useOperatorGuard()
  // 용어 이름은 신고된 용어로 채워 두고 고칠 수 있다(목업과 같다).
  const [label, setLabel] = useState(report.title)
  const [description, setDescription] = useState('')
  const [upload, setUpload] = useState<Upload | null>(null)
  // 거절된 파일이 입력 칸에 남지 않도록 칸을 새로 그린다.
  const [inputKey, setInputKey] = useState(0)
  const [imageError, setImageError] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  // 미리보기 주소는 쓰고 나면 해제한다.
  useEffect(
    () => () => {
      if (upload) URL.revokeObjectURL(upload.url)
    },
    [upload],
  )

  function handlePick(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return
    // 허용되지 않는 파일은 안내만 하고 저장 대상에 넣지 않는다.
    if (!isAllowedImage(file)) {
      setImageError(IMAGE_REJECTED_MESSAGE)
      setInputKey((value) => value + 1)
      return
    }
    setImageError('')
    setUpload({ file, url: URL.createObjectURL(file) })
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    if (!label.trim() || !description.trim()) {
      setError(MESSAGES.required)
      return
    }
    setBusy(true)
    setError('')
    try {
      await saveDictionaryEntry(report.id, { label: label.trim(), description: description.trim() }, upload?.file ?? null)
      navigate(operatorPaths.reports, { state: { notice: MESSAGES.saved } })
    } catch (failure) {
      // 권한 오류면 로그인 상태를 다시 읽어 경로 보호가 화면을 내보낸다. 그 밖에는 저장하지 못했다고 알린다.
      if (!onApiError(failure)) setError(MESSAGES.saveFailed)
      setBusy(false)
    }
  }

  return (
    <form className={styles.formCard} onSubmit={handleSubmit}>
      <h2 className={styles.formTitle}>사전 설명</h2>
      <TextField label="용어 이름" required maxLength={100} value={label} onChange={(event) => setLabel(event.target.value)} />
      <TextField
        label="바른 설명"
        multiline
        required
        className={styles.description}
        value={description}
        onChange={(event) => setDescription(event.target.value)}
      />
      <div className={styles.imageField}>
        {upload ? (
          <>
            <span className={styles.label}>이미지</span>
            <div className={styles.imageRow}>
              <img className={styles.image} src={upload.url} alt="설명 이미지 미리보기" />
              <Button
                onClick={() => {
                  setUpload(null)
                  setInputKey((value) => value + 1)
                }}
              >
                이미지 삭제
              </Button>
            </div>
          </>
        ) : null}
        <div>
          <label className={styles.label} htmlFor="correct-image">
            이미지 올리기 (선택, 한 장씩)
          </label>
          <input
            key={inputKey}
            id="correct-image"
            type="file"
            accept={IMAGE_TYPES.join(',')}
            aria-describedby={imageError ? 'correct-image-error' : undefined}
            onChange={handlePick}
          />
        </div>
        {imageError ? (
          <p id="correct-image-error" role="alert" className={styles.error}>
            오류: {imageError}
          </p>
        ) : null}
      </div>
      <p className={styles.notice}>{MESSAGES.notice}</p>
      {error ? (
        <p role="alert" className={styles.error}>
          오류: {error}
        </p>
      ) : null}
      <div className={styles.row}>
        <Button type="submit" variant="primary" aria-disabled={busy ? 'true' : undefined}>
          사전에 저장
        </Button>
        <Link to={operatorPaths.reports} className={styles.cancel}>
          취소
        </Link>
      </div>
    </form>
  )
}
