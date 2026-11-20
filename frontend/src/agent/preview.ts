// CS Agent 화면을 여는 임시 연결(MEG-258, T6c). 진입점 교체('AI 설명' → 'AI에게 질문')와 노출 중단 플래그 처리는 T6e(MEG-259)가 한다.
// 그 전까지는 개발 서버(import.meta.env.DEV)에서 주소에 ?cs-agent=1을 붙였을 때만 노트 선택 버튼이 CS Agent 패널을 연다.
// 제품 빌드(npm run build, Vercel)에서는 import.meta.env.DEV가 false로 바뀌어 이 조건이 늘 거짓이다. 사용자에게 새 입구가 보이지 않는다.
export const AGENT_PREVIEW_PARAM = 'cs-agent'

export function agentPreviewEnabled(search: URLSearchParams): boolean {
  return import.meta.env.DEV && search.get(AGENT_PREVIEW_PARAM) === '1'
}
