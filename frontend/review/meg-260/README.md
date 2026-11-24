# MEG-260 CS Agent 예외 상태 화면: 목업 대조 스크린샷

`screens/`의 이미지는 왼쪽에 캔버스 보드를, 오른쪽에 구현 화면을 놓았다(AC-1).

- **목업:** Claude Design 캔버스 Version 102의 F6 보드를 정적 HTML로 그려 찍었다(2026-11-20).
- **구현:** `tests/agentExceptions.spec.ts`가 가짜 API(`VITE_API_MOCK=true`)로 각 상태를 띄워 찍었다. 모델은 부르지 않았다. 답변 문구는 합성 문구다.
- **다시 만들기:** `frontend`에서 `$env:AGENT_SHOT_DIR='<폴더>'; npx playwright test tests/agentExceptions.spec.ts`
- **노트 근거 기간:** 캔버스는 위키 문구이고 구현은 디자인 v0.2 14.5의 노트 근거 기간 문구를 쓴다.
- **모바일:** 기존 보드가 있던 F6-8m·F6-11m·F6-13m·F6-15m만 비교한다. F6-12m·F6-12bm·F6-15bm·F6-20m은 T6g(MEG-263)다.
