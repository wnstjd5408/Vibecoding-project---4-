import type { ReactNode } from 'react'
import { Badge } from './Badge.tsx'

// AI가 만든 내용임을 알리는 연필색 배지. 문구 기본값은 "AI 생성"이다.
export function AiBadge({ children = 'AI 생성' }: { children?: ReactNode }) {
  return <Badge tone="ai">{children}</Badge>
}
