// 출처 보기(S10, E32) 상태. 출처를 열 때마다 서버가 권한을 다시 확인하므로 캐시하지 않고 열 때마다 부른다(spec E32).
// 404(볼 수 없는 출처)는 gone이다. 패널이 출처 보기를 닫고 대화를 E28로 다시 읽어 가린 턴(F6-15b)이나 접근 변경(F6-15)을 보여 준다.
import { useEffect, useState } from 'react'
import { isApiError } from '../api/client.ts'
import { readSource } from './api.ts'
import type { AgentSourceView } from './types.ts'

export type OpenSource = {
  turnId: string
  ref: number
  // 출처를 연 버튼. 대화로 돌아갈 때 포커스를 돌려준다.
  opener: HTMLElement | null
  // 출처를 연 횟수. 같은 출처를 다시 열어도 새로 부른다.
  openId: number
}

export type SourceState =
  | { status: 'loading' }
  | { status: 'loaded'; data: AgentSourceView }
  | { status: 'failed' }
  | { status: 'gone' }

export function useAgentSource(source: OpenSource | null): SourceState | null {
  const [result, setResult] = useState<{ openId: number; state: SourceState } | null>(null)
  const openId = source?.openId
  const turnId = source?.turnId
  const ref = source?.ref
  useEffect(() => {
    if (openId === undefined || turnId === undefined || ref === undefined) return
    const controller = new AbortController()
    readSource(turnId, ref, controller.signal).then(
      (data) => { if (!controller.signal.aborted) setResult({ openId, state: { status: 'loaded', data } }) },
      (error: unknown) => {
        if (!controller.signal.aborted) setResult({ openId, state: { status: isApiError(error, 'not_found') ? 'gone' : 'failed' } })
      },
    )
    return () => controller.abort()
  }, [openId, turnId, ref])
  if (source === null) return null
  return result?.openId === source.openId ? result.state : { status: 'loading' }
}
