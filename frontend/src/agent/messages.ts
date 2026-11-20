// CS Agent 'AI에게 질문' 화면 문구(MEG-258). 문구를 바꿀 때는 이 파일만 고친다.
// 출처: 캔버스 Version 96 보드(F6-1~F6-19), 디자인 v0.2 14.5 '노트 근거 기간' 표(사용자 결정 2026-11-18).
// '임시'라고 적은 문구는 캔버스와 디자인 문서에 없는 것이다(PR 본문에 목록을 남긴다).
import type { AgentQuestion, AgentStep, QuestionPreset, SourceKind } from './types.ts'

function sourceCard(kind: SourceKind, title: string, section?: string): string {
  return [kind === 'note' ? '노트' : null, title, section || null].filter(Boolean).join(' · ')
}

export const AGENT_MESSAGES = {
  title: 'AI에게 질문',
  newConversation: '새 대화',
  close: '닫기',
  // 보기 전환(F6-3·F6-3f·F6-3x, 결정 25·44)
  viewPanel: '패널로 보기',
  viewFloating: '창으로 보기',
  viewFullscreen: '전체 화면',
  backToNote: '노트로 돌아가기',
  topic: (label: string) => `현재 주제: ${label}`,
  contextWithSelection: '참고 문맥: 현재 노트 · 선택 영역',
  // 임시: 선택 문장을 제외한 뒤의 참고 문맥
  contextNoteOnly: '참고 문맥: 현재 노트',
  showSelection: '선택 내용 보기',
  selectionChip: (text: string) => `선택: ‘${text}’`,
  selectionFull: '전체 보기',
  exclude: '제외',
  // 임시: '선택 내용 보기'로 펼친 영역의 이름
  selectionRegion: '선택한 문장',

  // F6-1 질문 준비
  askIntro: '선택한 내용으로 질문할 수 있어요.',
  // 임시: 선택 문장을 제외해 빠른 질문을 쓸 수 없을 때
  askIntroNoSelection: '질문을 직접 써 주세요.',
  quickGroup: '빠른 질문',
  quickHint: '칩을 누르면 ‘이 부분을 자세히 설명해 줘.’처럼 질문을 바로 보내요. 아래 칸에 직접 써도 돼요.',

  // 입력 칸
  labelFirst: '질문하기',
  labelNext: '이어서 질문하기',
  labelKeep: '이어서 질문하기 · 입력한 내용은 그대로 남아요',
  labelKeepStopped: '이어서 질문하기 · 쓰던 내용은 그대로 남아요',
  labelLockedFailed: '이어서 질문하기 · 다시 시도하기 전에는 보내기를 쓸 수 없어요',
  labelLockedLimit: '이어서 질문하기 · 다시 확인하기 전에는 보내기를 쓸 수 없어요',
  placeholderFirst: '선택한 내용에 대해 질문해 보세요',
  placeholderNext: '이어서 질문해 보세요',
  send: '보내기',
  stop: '중단',

  // 대화
  question: '질문',
  // 이전 대화 보기 · ‘재시도’ 자세히 설명 (F6-7·F6-14·F6-6p·F6-17)
  previous: (topic: string, label: string) => (topic ? `이전 대화 보기 · ‘${topic}’ ${label}` : `이전 대화 보기 · ${label}`),
  // 임시: 이전 대화를 다시 읽지 못했을 때
  previousFailed: '오류: 이전 대화를 다시 불러오지 못했어요. 지금 보이는 대화는 그대로예요.',
  // 임시: 대화 기록 영역의 이름(F6-10의 role=log)
  log: '대화',
  newAnswer: '새 답변 보기',

  // S2 준비 중과 AI 추론 단계(F6-2·F6-2b·F6-2bm·F6-19, 결정 8~10, 14.5 노트 근거 기간)
  preparing: '답변을 준비하고 있어요.',
  stepsTitle: '답변을 준비하고 있어요',
  stepName: (step: AgentStep, kind: SourceKind | undefined): string =>
    step === 'understand' ? '질문 이해하기' : step === 'retrieve' ? (kind === 'wiki' ? '위키에서 자료 찾기' : '노트에서 자료 찾기') : '설명 정리하기',
  stepCurrent: '진행 중',
  stepUnderstood: (withSelection: boolean) => (withSelection ? '완료 · 선택한 문장과 질문을 확인했어요' : '완료 · 질문을 확인했어요'), // 선택 없는 경우는 임시
  stepRetrieved: (count: number | undefined, kind: SourceKind | undefined) =>
    count === undefined ? '완료' : `완료 · ${kind === 'wiki' ? '위키' : '노트'} 문단 ${count}개를 확인했어요`,
  stepDone: '완료',
  stepNow: (name: string, delayed: boolean) => `지금 단계: ${name}${delayed ? '. 평소보다 오래 걸리고 있어요.' : ''}`,
  delayedTitle: '평소보다 오래 걸리고 있어요.',
  delayedHelp: '계속 기다리거나 입력 칸의 중단 버튼으로 멈출 수 있어요.',

  // S3 답변
  aiBadge: 'AI 생성',
  references: '참고 자료',
  // 14.5: [1] 노트 · 노트 제목 · 절 제목 (위키는 캔버스 '[1] 예시 위키 · 재시도 문단' 형식)
  referenceLabel: (ref: number, kind: SourceKind, title: string, section?: string) => `[${ref}] ${sourceCard(kind, title, section)}`,
  suggestions: '이어서 궁금할 수 있는 질문',

  // S7 중단(F6-14·F6-14b·F6-14m)
  stopped: '응답을 중단했어요.',
  stoppedHidden: '중단한 답변은 보여 주지 않아요.',
  reinsert: '중단한 질문 다시 넣기',
  reinsertHint: '입력 칸에 쓰던 내용이 있으면 바꾸기 전에 먼저 물어봐요.',
  replaceTitle: '쓰던 내용을 중단한 질문으로 바꿀까요?',
  replaceCurrent: '지금 쓰던 내용',
  replaceNext: '바꿀 질문',
  replace: '바꾸기',
  cancel: '취소',
  replaceHint: '취소하면 쓰던 내용을 그대로 둬요.',

  // S8 요청 실패(F6-6p·F6-6)
  failed: '오류: 답변을 가져오지 못했어요. 질문은 보관했어요.',
  failedHelp: '다시 시도하면 같은 질문으로 요청해요. 이미 보낸 요청은 먼저 확인해서 중복으로 보내지 않아요.',
  retry: '다시 시도',

  // S12 사용 제한(F6-17)
  limited: '오류: 지금은 AI 답변을 요청할 수 없어요.',
  limitedHelp: '쓰던 내용은 아래 칸에 남겨 두었어요. 노트는 계속 읽을 수 있어요.',
  recheck: '다시 확인',
  keepReading: '노트 계속 읽기',

  // 예외 상태(MEG-260, T6d). 출처: 캔버스 Version 102 보드 F6-8·F6-11·F6-12·F6-12b·F6-13·F6-15·F6-15b·F6-20과 모바일 짝,
  // 디자인 v0.2 14.5 '노트 근거 기간' 표, F6-12b 두 번째 문장은 2026-11-20 문장 A.
  // S4 의미 확인(F6-11·F6-11m). 고르기 전에는 답변을 만들지 않는다. PC 보드의 '‘재시도 간격은 어떻게 정해?’처럼'은 예시라 모바일 문장을 쓴다.
  clarifyHelp: '고르면 그 내용으로 이어서 질문해요. 둘 다 아니면 아래 칸에 직접 적어 주세요.',
  labelClarify: '이어서 질문하기 · 직접 보충해도 돼요',
  // S5 근거 일부만 확인(F6-12). 한계 문장은 서버 limitation을 그대로 쓴다(노트 근거 기간 '참고한 노트에는 …').
  partialUnconfirmed: '확인하지 못한 부분',
  labelPartial: '이어서 질문하기 · 더 구체적으로 물어볼 수 있어요',
  // S5 근거 없음·무관(F6-12b). 첫 문장은 14.5 노트 근거 기간 문구, 두 번째 문장은 문장 A(2026-11-20 결정).
  noEvidenceTitle: (kind: SourceKind) => (kind === 'wiki' ? '참고할 수 있는 위키 자료를 찾지 못했어요.' : '참고할 수 있는 노트 자료를 찾지 못했어요.'),
  noEvidenceHelp: '그래서 이 질문에는 설명을 확정해 드릴 수 없어요. 선택한 문장과 가까운 내용으로 질문을 좁히거나 노트로 돌아갈 수 있어요.',
  labelNoEvidence: '이어서 질문하기 · 질문을 바꿔 다시 물어볼 수 있어요',
  // S6 확인된 교정(F6-13·F6-13m). 노트 근거 기간에는 서버가 correction을 내지 않는다(14.5).
  correctionTitle: '노트에서 확인할 부분',
  correctionNote: '노트 문장',
  correctionBasis: (kind: SourceKind) => (kind === 'wiki' ? '위키 문단 기준' : '노트 문단 기준'),
  correctionUnresolved: '확인하지 못한 부분',
  correctionNoEdit: '노트는 자동으로 고치지 않아요.',
  quoted: (text: string) => `“${text}”`,
  // 주제 전환 확인(F6-20, 결정 38·40). 고르기 전에는 보내기를 잠근다.
  topicTitle: (topic: string) => `지금 주제(${topic})와 다른 질문 같아요. 새 대화로 질문할까요?`,
  topicHelp: '새 대화로 질문하면 앞 대화와 선택한 문장은 빼고, 이 질문만으로 새 대화를 시작해요. 이 대화에서 계속하면 앞 대화를 함께 참고해요.',
  topicNew: '새 대화로 질문',
  topicContinue: '이 대화에서 계속',
  // W5 다른 영역 선택(F6-8·F6-8m, 결정 20)
  addTitle: '새로 선택한 내용을 어떻게 쓸까요?',
  addQuote: (text: string) => `‘${text}’`,
  addToConversation: '현재 대화에 추가',
  addNewConversation: '이 내용으로 새 대화',
  addHint: '고르기 전까지 다음 질문의 문맥은 바뀌지 않아요.',
  // S9 변형: 출처만 권한 회수(F6-15b, 결정 7·11·15·17). 다시 묻기를 쓸 수 없으면 마지막 문장의 뒤쪽을 뺀다.
  hiddenTitle: '이 답변에 쓴 자료를 더 이상 볼 수 없어요.',
  hiddenHelp: '그래서 이 답변과 출처, 그리고 이 답변을 바탕으로 한 뒤쪽 답변과 추천 질문을 함께 가렸어요. 가린 내용은 다음 질문에 쓰지 않아요.',
  hiddenKept: (canRetry: boolean) => (canRetry ? '노트와 내 질문은 그대로 있어요. 같은 질문을 다시 하면 지금 볼 수 있는 자료로 다시 찾아봐요.' : '노트와 내 질문은 그대로 있어요.'),
  askAgain: '같은 질문 다시 하기',
  hiddenFollowing: '앞 답변을 바탕으로 한 답변이라 함께 가렸어요. 필요하면 이 질문을 다시 보내 주세요.',
  // 임시: 가린 추천 질문 턴은 서버가 질문 글을 빼서 보여 줄 글이 없다(agent_access.turn_payload).
  hiddenSuggested: '가린 답변에서 고른 추천 질문이라 질문 글도 함께 가렸어요.',
  // S9 노트 접근 변경(F6-15·F6-15m, 결정 3)
  accessTitle: '이 자료를 더 이상 볼 수 없어요',
  accessClosed: '이 자료로 나눈 대화와 출처를 함께 닫았어요.',
  accessHelp: '볼 수 있는 노트를 골라 다시 읽거나 새로 질문할 수 있어요.',
  accessToList: '노트 목록으로 가기',
  accessList: '노트 목록',

  // S10 출처 보기(F6-4·F6-9, 14.5 노트 근거 기간. '노트 열기'는 넣지 않는다: 2026-11-20 결정 9)
  sourceTitle: (ref: number) => `출처 ${ref}`,
  // 출처 카드 글(F6-4·F6-9 머리 아래 줄). 참고 자료 줄과 같은 규칙에서 번호만 뺐다.
  sourceCard: (kind: SourceKind, title: string, section?: string) => sourceCard(kind, title, section),
  backToConversation: '대화로 돌아가기',
  sourceKindLabel: (kind: SourceKind) => (kind === 'wiki' ? '내부 위키' : 'CS 노트'),
  sourceGuide: (kind: SourceKind) =>
    kind === 'wiki'
      ? '왼쪽 위키에서 인용된 문단을 표시했어요. 질문할 때 선택한 노트 문장은 질문 문맥으로만 쓰였어요.'
      : '왼쪽에 인용한 노트 문단을 표시했어요. 질문할 때 선택한 문장은 근거로 쓰지 않았어요.',
  sourceChanged: '인용한 뒤 노트가 바뀌었어요. 인용할 때의 문단을 보여 드려요.',
  conversationKept: '대화는 그대로 있어요',
  sourceQuestion: (text: string) => `질문: ${text}`,
  sourceQuote: (text: string) => `답변에서 인용한 부분: “${text}”`,
  sourceReturnHint: '돌아가면 읽던 답변 위치와 입력 초안이 그대로 있어요.',
  // 임시: E32를 기다리는 동안과 실패했을 때
  sourceLoading: '출처를 불러오는 중이에요',
  sourceFailed: '오류: 출처를 불러오지 못했어요.',
}

// 빠른 질문 칩(결정 23). 'detail'의 질문 글은 F6-1 안내문과 F6-2b를 따랐고, 나머지 둘은 같은 형식으로 만든 임시 문구다.
export const PRESETS: { preset: QuestionPreset; label: string; text: string }[] = [
  { preset: 'detail', label: '자세히 설명', text: '이 부분을 자세히 설명해 줘.' },
  { preset: 'simple', label: '쉽게 풀어 줘', text: '이 부분을 쉽게 풀어 줘.' },
  { preset: 'example', label: '예시로 보여 줘', text: '이 부분을 예시로 보여 줘.' },
]

// 화면에 보여 줄 질문 글. 빠른 질문은 칩의 질문 글을 쓴다(서버는 모델에 넘길 고정 문구로 바꾼다).
export function questionText(question: Pick<AgentQuestion, 'kind' | 'text' | 'preset'>): string {
  if (question.kind === 'preset') return PRESETS.find((item) => item.preset === question.preset)?.text ?? question.text ?? ''
  return question.text ?? ''
}

// '이전 대화 보기' 줄에 붙이는 짧은 이름. 빠른 질문은 칩 이름('자세히 설명'), 그 밖은 질문 앞부분이다.
export function questionLabel(question: Pick<AgentQuestion, 'kind' | 'text' | 'preset'>): string {
  if (question.kind === 'preset') return PRESETS.find((item) => item.preset === question.preset)?.label ?? ''
  const text = (question.text ?? '').replace(/\s+/g, ' ').trim()
  return text.length > 20 ? `${text.slice(0, 20)}…` : text
}

// 서버의 주제 이름 규칙(backend/app/agent.py topic_label_of)과 같다. 대화를 만들기 전(E27 전)에 질문 준비 화면에 보여 준다.
export function topicLabelOf(text: string): string {
  return [...text.replace(/\s+/g, ' ').trim()].slice(0, 20).join('')
}
