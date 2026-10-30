// F5-2 신고 목록(MEG-84). 열린 신고를 보고 처리 완료로 바꾼다. 처리할 때 AI 설명을 무효화할지 고른다(Q-N7).
import { useEffect, useState } from 'react'
import type { ChangeEvent } from 'react'
import { useLocation } from 'react-router'
import { Button, LinkButton, StateMessage } from '../../components/index.ts'
import { Badge } from '../../components/Badge.tsx'
import { reportCorrectPath } from '../../routes/paths.ts'
import { useOperatorGuard } from '../useOperatorGuard.ts'
import { ResolveDialog } from './ResolveDialog.tsx'
import { listReports, resolveReport } from './reportsApi.ts'
import type { Report, ReportStatus } from './reportsApi.ts'
import styles from './Reports.module.css'

// 화면 문구. 실패 안내는 목업에 화면이 없어 임시 문구다(문구 미정, 확정되면 이 한 곳만 고친다).
const MESSAGES = {
  resolveFailed: '처리하지 못했어요. 잠시 뒤에 다시 시도해 주세요.',
  resolved: '신고를 처리했어요.',
} as const

type Result = { query: string; reports: Report[] } | { query: string; failed: true }

// 사전에 바른 설명을 저장한 뒤 이 화면으로 올 때 넘겨 준 안내
function readNotice(state: unknown): string {
  const value = (state as { notice?: unknown } | null)?.notice
  return typeof value === 'string' ? value : ''
}

export default function ReportsPage() {
  const location = useLocation()
  const { onApiError } = useOperatorGuard()
  const [status, setStatus] = useState<ReportStatus>('open')
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<Result | null>(null)
  const [target, setTarget] = useState<Report | null>(null)
  const [busy, setBusy] = useState(false)
  const [dialogError, setDialogError] = useState('')
  const [notice, setNotice] = useState(() => readNotice(location.state))

  // 필터를 바꾸거나 다시 시도하면 이전 결과는 버린다.
  const query = `${status}:${attempt}`
  const current = result?.query === query ? result : null

  useEffect(() => {
    let live = true
    listReports(status).then(
      (reports) => live && setResult({ query: `${status}:${attempt}`, reports }),
      (failure) => {
        if (!live || onApiError(failure)) return
        setResult({ query: `${status}:${attempt}`, failed: true })
      },
    )
    return () => {
      live = false
    }
  }, [status, attempt, onApiError])

  function closeDialog() {
    setTarget(null)
    setDialogError('')
  }

  async function handleResolve(invalidateExplanation: boolean) {
    if (!target || busy) return
    setBusy(true)
    setDialogError('')
    try {
      await resolveReport(target.id, { invalidateExplanation })
      // 처리한 신고는 이 목록(열림)에서 빠진다.
      setResult((old) => (old && 'reports' in old ? { ...old, reports: old.reports.filter((report) => report.id !== target.id) } : old))
      setNotice(MESSAGES.resolved)
      closeDialog()
    } catch (failure) {
      // 권한 오류면 로그인 상태를 다시 읽어 경로 보호가 화면을 내보낸다. 그 밖에는 창 안에서 알린다.
      if (!onApiError(failure)) setDialogError(MESSAGES.resolveFailed)
    }
    setBusy(false)
  }

  return (
    <main>
      <div className={styles.head}>
        <h1 className={styles.title}>신고</h1>
        <div className={styles.row}>
          <label className={styles.filterLabel} htmlFor="report-filter">
            상태
          </label>
          <select
            id="report-filter"
            className={styles.filterSelect}
            value={status}
            onChange={(event: ChangeEvent<HTMLSelectElement>) => {
              setNotice('')
              setStatus(event.target.value as ReportStatus)
            }}
          >
            <option value="open">열림</option>
            <option value="resolved">처리됨</option>
          </select>
        </div>
      </div>

      {notice ? (
        <p role="status" className={styles.status}>
          {notice}
        </p>
      ) : null}

      {!current ? (
        <StateMessage kind="loading" title="신고를 불러오는 중이에요" />
      ) : 'failed' in current ? (
        <StateMessage
          kind="error"
          title="신고를 불러오지 못했어요"
          description="잠시 뒤에 다시 시도해 주세요."
          action={<Button onClick={() => setAttempt((count) => count + 1)}>다시 시도</Button>}
        />
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <caption>
              {status === 'resolved' ? '처리된' : '열린'} 신고 {current.reports.length}건
            </caption>
            <thead>
              <tr>
                <th scope="col">종류</th>
                <th scope="col">신고된 내용</th>
                <th scope="col">동작</th>
              </tr>
            </thead>
            <tbody>
              {current.reports.map((report) => (
                <tr key={report.id}>
                  <td>
                    <Badge tone="ai">AI 생성</Badge>
                    <p className={styles.kind}>{report.kind}</p>
                  </td>
                  <td>
                    <h2 className={styles.reportTitle}>{report.title}</h2>
                    <p className={styles.reportBody}>{report.body}</p>
                  </td>
                  <td>
                    <div className={styles.actions}>
                      {report.kind === '용어 설명' ? (
                        <LinkButton variant="primary" to={reportCorrectPath(report.id)}>
                          사전에 바른 설명 넣기
                        </LinkButton>
                      ) : null}
                      {!report.resolved ? <Button onClick={() => setTarget(report)}>처리됨으로 표시</Button> : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {current.reports.length === 0 ? <p className={styles.empty}>이 상태의 신고가 없어요.</p> : null}
        </div>
      )}

      {target ? (
        <ResolveDialog report={target} busy={busy} error={dialogError} onConfirm={handleResolve} onClose={closeDialog} />
      ) : null}
    </main>
  )
}
