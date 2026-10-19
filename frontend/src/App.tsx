import { useEffect, useState } from 'react'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

type HealthState =
  | { kind: 'loading' }
  | { kind: 'ok'; status: string }
  | { kind: 'error'; message: string }

function App() {
  const [health, setHealth] = useState<HealthState>({ kind: 'loading' })

  useEffect(() => {
    fetch(`${API_BASE_URL}/health`)
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const body: { status: string } = await response.json()
        setHealth({ kind: 'ok', status: body.status })
      })
      .catch((error: unknown) => {
        const message = error instanceof Error ? error.message : String(error)
        setHealth({ kind: 'error', message })
      })
  }, [])

  return (
    <main style={{ padding: '2rem' }}>
      <h1>Vibecoding project 4</h1>
      <p>
        백엔드 상태 (<code>{API_BASE_URL}/health</code>):{' '}
        {health.kind === 'loading' && '확인 중…'}
        {health.kind === 'ok' && <strong>{health.status}</strong>}
        {health.kind === 'error' && <strong>연결 실패 — {health.message}</strong>}
      </p>
    </main>
  )
}

export default App
