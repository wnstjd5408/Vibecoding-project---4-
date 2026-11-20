// 시험 전용 화면(MEG-256). 컴포넌트 시험 도구 없이 개발 서버가 이 파일을 그대로 내보내고, 시험이 페이지 안에서 불러와 AiAnswer를 그린다.
// 제품 빌드(src만 포함)에는 들어가지 않는다. 단계 목록은 패널에서 답변 옆에 있는 글을 흉내 낸 것이다(실제 배치는 T6c).
import { createRoot } from 'react-dom/client'
import type { Root } from 'react-dom/client'
import { AiAnswer } from '../../src/notes/AiAnswer.tsx'
import type { AiAnswerFigure, AiAnswerSection, AiAnswerSource } from '../../src/notes/AiAnswer.tsx'

type Fixture = { sections: AiAnswerSection[]; figures?: AiAnswerFigure[]; sources?: AiAnswerSource[]; steps?: string[] }

declare global {
  interface Window { __sourceClicks: number[] }
}

let root: Root | null = null

// 처음 부르면 그리고, 다시 부르면 같은 자리에 새 값으로 다시 그린다(다음 답변이 같은 자리에 오는 경우).
export function mount(fixture: Fixture) {
  if (root === null) {
    document.getElementById('root')?.setAttribute('hidden', '')
    const host = document.createElement('div')
    host.id = 'harness'
    document.body.append(host)
    window.__sourceClicks = []
    root = createRoot(host)
  }
  root.render(<main>
    <ol data-testid="steps">{(fixture.steps ?? []).map((step) => <li key={step}>{step}</li>)}</ol>
    <div data-testid="answer">
      <AiAnswer sections={fixture.sections} figures={fixture.figures} sources={fixture.sources} onSource={(ref) => { window.__sourceClicks.push(ref) }} />
    </div>
  </main>)
}
