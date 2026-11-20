// CS Agent E27~E32 호출 함수(API spec v0.2 4절, MEG-255). 화면은 이 함수들을 직접 부르지 않고 agent/conversation.ts의 대화 상태를 쓴다.
// E27·E28·E30·E31·E32는 JSON이라 공용 apiFetch를 쓴다. E29는 POST에 SSE 응답이라 fetch 본문을 직접 읽는다.
// 가짜 응답을 쓸지는 다른 화면처럼 VITE_API_MOCK 한 곳(api/source.ts)이 정한다. E29의 가짜 SSE는 api/mocks/agent.ts에 있다.
import { ApiError, CLIENT_ERROR_CODES, apiFetch } from '../api/client.ts'
import { openMockTurnStream } from '../api/mocks/agent.ts'
import { getApiSource } from '../api/source.ts'
import type { ApiErrorBody } from '../api/types.ts'
import { readSse, toTurnEvent } from './sse.ts'
import type {
  AgentCancelResponse,
  AgentConversation,
  AgentConversationWithTurns,
  AgentSourceView,
  AgentTurnRead,
  AskTurnRequest,
  CreateConversationRequest,
  TurnEvent,
} from './types.ts'

const path = (id: string) => encodeURIComponent(id)

// E27 대화 만들기. 모델을 부르지 않는다. 노트 문맥이면 선택 위치는 코드포인트 위치다(ai/explain.ts toCodePointRange).
export function createConversation(request: CreateConversationRequest, signal?: AbortSignal): Promise<AgentConversation> {
  return apiFetch<AgentConversation>('/api/ai/conversations', { method: 'POST', body: request, signal })
}

// E28 대화와 턴 목록(오래된 순, 가림 적용)
export function readConversation(conversationId: string, signal?: AbortSignal): Promise<AgentConversationWithTurns> {
  return apiFetch<AgentConversationWithTurns>(`/api/ai/conversations/${path(conversationId)}`, { signal })
}

// E30 턴 다시 읽기. running이면 retry_after_seconds 뒤에 다시 부른다.
export function readTurn(turnId: string, signal?: AbortSignal): Promise<AgentTurnRead> {
  return apiFetch<AgentTurnRead>(`/api/ai/turns/${path(turnId)}`, { signal })
}

// E31 응답 중단. 이미 끝났으면 409 conflict/turn_not_cancellable이다.
export function cancelTurn(turnId: string, signal?: AbortSignal): Promise<AgentCancelResponse> {
  return apiFetch<AgentCancelResponse>(`/api/ai/turns/${path(turnId)}/cancel`, { method: 'POST', signal })
}

// E32 출처 보기. 열 때마다 서버가 권한을 다시 확인한다. 볼 수 없으면 404다.
export function readSource(turnId: string, ref: number, signal?: AbortSignal): Promise<AgentSourceView> {
  return apiFetch<AgentSourceView>(`/api/ai/turns/${path(turnId)}/sources/${ref}`, { signal })
}

function clientError(status: number, code: string, message: string): ApiError {
  return new ApiError(status, { code, message, request_id: '' })
}

// E29 질문하기. 스트림이 열리기 전의 거절(400·401·403·404·409·422·429·503)은 ApiError로 던진다.
// 열리면 이벤트를 하나씩 돌려준다. 읽는 중에 연결이 끊기면 읽기 오류를 그대로 던지고, 부른 쪽이 E30으로 결과를 받는다.
// idempotencyKey는 사용자 동작 하나에 하나다. 같은 동작을 다시 보낼 때(응답을 못 받은 경우 등)는 같은 키를 넘긴다.
export async function openTurnStream(
  conversationId: string,
  request: AskTurnRequest,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<AsyncGenerator<TurnEvent>> {
  const url = `/api/ai/conversations/${path(conversationId)}/turns`
  if (getApiSource() === 'mock') {
    const opened = openMockTurnStream({ conversationId, body: request, key: idempotencyKey, signal })
    if ('stream' in opened) return turnEvents(opened.stream)
    throw toApiError(opened.status, opened.body)
  }
  let response: Response
  try {
    response = await fetch(url, {
      method: 'POST',
      credentials: 'include',
      headers: { Accept: 'text/event-stream', 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify(request),
      signal,
    })
  } catch (cause) {
    if (signal?.aborted) throw cause
    // 서버가 요청을 받았는지 모른다. 부른 쪽은 같은 키로 다시 보낸다(끝난 턴은 재생, 진행 중이면 409 in_progress).
    throw clientError(0, CLIENT_ERROR_CODES.networkError, 'Network request failed')
  }
  if (!response.ok) {
    const text = await response.text().catch(() => '')
    let body: unknown
    try {
      body = text ? JSON.parse(text) : undefined
    } catch {
      body = undefined
    }
    throw toApiError(response.status, body)
  }
  const type = response.headers.get('Content-Type') ?? ''
  if (!type.includes('text/event-stream') || response.body === null) {
    // 프록시가 앱 HTML을 돌려준 경우 등. 처리 여부를 모르므로 응답을 못 받은 경우와 같이 다룬다.
    response.body?.cancel().catch(() => {})
    throw clientError(response.status, CLIENT_ERROR_CODES.unexpectedResponse, 'Unexpected response')
  }
  return turnEvents(response.body)
}

function toApiError(status: number, body: unknown): ApiError {
  const error = (body as ApiErrorBody | undefined)?.error
  if (typeof error?.code === 'string') return new ApiError(status, error)
  return clientError(status, CLIENT_ERROR_CODES.unexpectedResponse, 'Unexpected response')
}

async function* turnEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<TurnEvent> {
  for await (const message of readSse(body)) {
    const event = toTurnEvent(message)
    if (event) yield event
  }
}
