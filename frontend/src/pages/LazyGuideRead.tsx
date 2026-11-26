import { Component, lazy, Suspense, type ReactNode } from 'react'
import { Button, StateMessage } from '../components/index.ts'

// 가이드 화면(MEG-288)은 노트 화면 번들에 넣지 않고 /guides/:slug에 들어갈 때만 불러온다(PRD v0.5 5.2절).
const GuideReadPage = lazy(() => import('./GuideReadPage.tsx'))

// 화면 묶음 자체를 받지 못하면(배포 교체 직후, 네트워크 끊김) 오류와 다시 시도를 보인다(PRD AC-10).
// 같은 탭에서 다시 받으려면 새로 고쳐야 해서 다시 시도는 페이지를 새로 고친다.
class ChunkBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  render() {
    if (!this.state.failed) return this.props.children
    return (
      <main style={{ padding: 'var(--space-6) var(--space-4)' }}>
        <StateMessage kind="error" title="가이드를 불러오지 못했어요" headingLevel={2}
          action={<Button variant="primary" onClick={() => window.location.reload()}>다시 시도</Button>} />
      </main>
    )
  }
}

export function GuideRoute() {
  return (
    <ChunkBoundary>
      <Suspense fallback={<p role="status">가이드를 불러오는 중…</p>}>
        <GuideReadPage />
      </Suspense>
    </ChunkBoundary>
  )
}
