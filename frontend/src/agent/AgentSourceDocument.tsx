// PC 출처 보기의 문서 쪽(F6-4 왼쪽, 디자인 v0.2 14.5 노트 근거 기간). 노트 본문 자리에 인용 당시 문단과 절 제목을 보여 준다.
// 대화는 오른쪽 패널에 그대로 있고, '대화로 돌아가기'를 누르면 읽던 노트와 위치로 돌아간다(9절).
// '노트 열기'는 넣지 않는다(2026-11-20 결정 9).
import { SourceParagraph } from './AgentPanel.tsx'
import { AGENT_MESSAGES as M } from './messages.ts'
import type { SourceState } from './useAgentSource.ts'
import styles from './AgentSourceDocument.module.css'

export function AgentSourceDocument({ state, ref_ }: { state: SourceState; ref_: number }) {
  if (state.status === 'loading') return <p role="status" className={styles.meta}>{M.sourceLoading}</p>
  if (state.status === 'failed') return <p role="alert" className={styles.error}>{M.sourceFailed}</p>
  const { data } = state
  return <article className={styles.article} aria-label={M.sourceTitle(ref_)}>
    <h1 className={styles.title}>{data.title}</h1>
    <p className={styles.meta}>{M.sourceKindLabel(data.source_kind)}</p>
    {data.changed_since_cited ? <p className={styles.changed}>{M.sourceChanged}</p> : null}
    <SourceParagraph ref_={ref_} text={data.paragraph_text} section={data.section} />
  </article>
}
