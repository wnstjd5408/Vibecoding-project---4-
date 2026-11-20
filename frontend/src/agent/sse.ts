// E29 응답(text/event-stream)을 읽는 파서(API spec v0.2 6절, MEG-255).
// E29는 POST라 브라우저 EventSource를 쓸 수 없어 fetch 응답 본문을 직접 읽는다. 규칙은 HTML 표준의 event stream 해석을 따른다.
//  - 줄 끝은 CRLF·LF·CR 모두 받는다. 조각 경계에서 CR 뒤에 LF가 올 수 있어 CR로 끝난 조각은 다음 조각까지 기다린다.
//  - ':'로 시작하는 줄은 주석이다(서버의 keep-alive). 빈 줄에서 이벤트 하나를 내보낸다. data 줄이 여럿이면 줄바꿈으로 잇는다.
//  - 스트림이 빈 줄 없이 끝나면 마지막 미완성 이벤트는 버린다(표준과 같다). 끊긴 스트림의 반쪽 이벤트를 쓰지 않기 위해서다.
import type { TurnEvent } from './types.ts'

export type SseMessage = { event: string; data: string }

export class SseParser {
  private buffer = ''
  private event = ''
  private data: string[] = []
  private started = false

  // 받은 글자를 넣고, 이번에 끝난 이벤트들을 돌려준다.
  push(text: string): SseMessage[] {
    this.buffer += text
    if (!this.started && this.buffer.length > 0) {
      this.started = true
      if (this.buffer.charCodeAt(0) === 0xfeff) this.buffer = this.buffer.slice(1)
    }
    const messages: SseMessage[] = []
    let at = 0
    for (;;) {
      const lf = this.buffer.indexOf('\n', at)
      const cr = this.buffer.indexOf('\r', at)
      if (lf < 0 && cr < 0) break
      let end: number
      let next: number
      if (cr >= 0 && (lf < 0 || cr < lf)) {
        // CR로 끝난 조각이면 뒤에 LF가 올지 모르므로 기다린다.
        if (cr === this.buffer.length - 1) break
        end = cr
        next = this.buffer[cr + 1] === '\n' ? cr + 2 : cr + 1
      } else {
        end = lf
        next = lf + 1
      }
      const message = this.line(this.buffer.slice(at, end))
      if (message) messages.push(message)
      at = next
    }
    this.buffer = this.buffer.slice(at)
    return messages
  }

  // 스트림이 끝났을 때 부른다. 기다리던 CR은 줄 끝으로 보고 처리한 뒤, 빈 줄로 닫히지 않은 이벤트는 버린다.
  end(): SseMessage[] {
    const messages: SseMessage[] = []
    if (this.buffer.endsWith('\r')) {
      const message = this.line(this.buffer.slice(0, -1))
      if (message) messages.push(message)
    }
    this.buffer = ''
    this.event = ''
    this.data = []
    return messages
  }

  private line(line: string): SseMessage | null {
    if (line === '') {
      if (this.data.length === 0) {
        this.event = ''
        return null
      }
      const message = { event: this.event || 'message', data: this.data.join('\n') }
      this.event = ''
      this.data = []
      return message
    }
    if (line.startsWith(':')) return null
    const colon = line.indexOf(':')
    const field = colon < 0 ? line : line.slice(0, colon)
    let value = colon < 0 ? '' : line.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') this.event = value
    else if (field === 'data') this.data.push(value)
    // id·retry는 쓰지 않는다. 끊기면 다시 연결하지 않고 E30으로 결과를 받는다.
    return null
  }
}

// 응답 본문을 읽어 이벤트를 하나씩 돌려준다. 연결이 끊기면 읽기 오류를 그대로 던진다(부른 쪽이 E30 복구로 넘어간다).
export async function* readSse(body: ReadableStream<Uint8Array>): AsyncGenerator<SseMessage> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  const parser = new SseParser()
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) {
        yield* parser.push(decoder.decode())
        yield* parser.end()
        return
      }
      yield* parser.push(decoder.decode(value, { stream: true }))
    }
  } finally {
    // 끝까지 읽지 않고 멈춘 경우(result를 받았거나 중단·화면 이탈) 연결을 닫는다. 서버 실행은 연결과 무관하게 끝까지 간다.
    reader.cancel().catch(() => {})
  }
}

// 6절 이벤트 이름과 data를 화면이 쓰는 모양으로 바꾼다. 모르는 이벤트는 null(무시)이다.
// data가 JSON이 아니면 서버 계약 위반이라 오류를 던진다. 부른 쪽은 스트림이 끊긴 것과 같이 E30으로 확인한다.
export function toTurnEvent(message: SseMessage): TurnEvent | null {
  switch (message.event) {
    case 'turn':
    case 'step':
    case 'result':
    case 'error': {
      const data = JSON.parse(message.data) as unknown
      if (typeof data !== 'object' || data === null) throw new SyntaxError('Unexpected event data')
      if (message.event === 'error') {
        const error = (data as { error?: unknown }).error
        if (typeof error !== 'object' || error === null) throw new SyntaxError('Unexpected error event')
        return { type: 'error', data: error as Extract<TurnEvent, { type: 'error' }>['data'] }
      }
      return { type: message.event, data } as TurnEvent
    }
    case 'delayed':
      return { type: 'delayed' }
    default:
      return null
  }
}
