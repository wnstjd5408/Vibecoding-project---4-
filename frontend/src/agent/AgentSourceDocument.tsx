// PC 출처 보기의 문서 쪽(F6-4 왼쪽, 디자인 v0.2 14.5 노트 근거 기간). 노트 본문 자리에 인용 당시 문단과 절 제목을 보여 준다.
// 대화는 오른쪽 패널에 그대로 있고, '대화로 돌아가기'를 누르면 읽던 노트와 위치로 돌아간다(9절).
// '노트 열기'는 넣지 않는다(2026-11-20 결정 9).
// 위키 출처(F6-4 위키, MEG-254)는 같은 구조에 '용어 시트 열기'를 더한다. 누르면 노트 화면이 대화 패널을 닫고 그 용어 시트(E06)를 연다.
import { Link } from 'react-router'
import { userPaths } from '../routes/paths.ts'
import { OpenTermButton, SourceParagraph } from './AgentPanel.tsx'
import { AGENT_MESSAGES as M } from './messages.ts'
import type { SourceState } from './useAgentSource.ts'
import type { OpenTerm } from './types.ts'
import styles from './AgentSourceDocument.module.css'

export function AgentSourceDocument({ state, ref_, onOpenTerm }: { state: SourceState; ref_: number; onOpenTerm?: OpenTerm }) {
  // gone(404)이면 패널이 곧 출처 보기를 닫는다. 그동안은 불러오는 중으로 둔다.
  if (state.status === 'loading' || state.status === 'gone') return <p role="status" className={styles.meta}>{M.sourceLoading}</p>
  if (state.status === 'failed') return <p role="alert" className={styles.error}>{M.sourceFailed}</p>
  const { data } = state
  return <article className={styles.article} aria-label={M.sourceTitle(ref_)}>
    <h1 className={styles.title}>{data.title}</h1>
    <p className={styles.meta}>{M.sourceKindLabel(data.source_kind)}</p>
    {data.changed_since_cited ? <p className={styles.changed}>{M.sourceChanged(data.source_kind)}</p> : null}
    <SourceParagraph ref_={ref_} text={data.paragraph_text} section={data.section} />
    <OpenTermButton data={data} onOpenTerm={onOpenTerm} />
  </article>
}

// S9 노트 접근 변경(F6-15, 결정 3). 노트를 더 볼 수 없으면 노트 본문 자리를 이 안내로 바꾸고 노트 목록으로 가는 길만 둔다(MEG-260).
export function AgentAccessLostDocument() {
  return <section className={styles.lost} aria-labelledby="agent-access-lost">
    <h1 id="agent-access-lost" className={styles.lostTitle}>{M.accessTitle}</h1>
    <p className={styles.lostText}>{M.accessHelp}</p>
    <Link to={userPaths.noteList} className={styles.lostLink}>{M.accessToList}</Link>
  </section>
}
