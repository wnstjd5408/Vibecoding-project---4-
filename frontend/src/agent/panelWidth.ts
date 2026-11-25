// CS Agent PC 패널 폭 조절(MEG-285). 캔버스 F6-21a~e, 2026-11-25 사람 승인.
//  - 기본 480px, 최소 400px, 최대 720px. 노트 영역이 480px보다 좁아지지 않게 화면이 좁으면 최대를 줄인다(1024px 화면이면 544px).
//  - 바꾼 폭은 기억하지 않는다. 패널을 닫았다 열면 480px로 시작한다(사람 결정).
//  - 패널 보기에서만 쓴다. 떠 있는 창·전체 화면·모바일과 용어·로그인 패널은 기존 폭 그대로다.
export const PANEL_WIDTH_DEFAULT = 480
export const PANEL_WIDTH_MIN = 400
export const PANEL_WIDTH_MAX = 720
// 패널을 넓혀도 남겨 둘 노트 영역의 폭
export const PANEL_NOTE_MIN = 480
// 키보드 방향키 한 번에 바뀌는 폭
export const PANEL_WIDTH_STEP = 16

// 화면 폭(스크롤 막대를 뺀 폭)에서 쓸 수 있는 최대 패널 폭
export function maxPanelWidth(viewport: number): number {
  return Math.max(PANEL_WIDTH_MIN, Math.min(PANEL_WIDTH_MAX, viewport - PANEL_NOTE_MIN))
}

export function clampPanelWidth(width: number, viewport: number): number {
  return Math.round(Math.min(maxPanelWidth(viewport), Math.max(PANEL_WIDTH_MIN, width)))
}

export const viewportWidth = () => document.documentElement.clientWidth
