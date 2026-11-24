# MEG-263 CS Agent 모바일 보충 보드: 목업 대조 스크린샷

`screens/`의 이미지는 왼쪽에 캔버스 보드를, 오른쪽에 구현 화면(390×844)을 놓았다(AC-1).

- **목업:** Claude Design 캔버스의 'CS Agent 모바일 보충 · MEG-262' 줄 보드 10장을 정적 HTML로 그려 찍었다(2026-11-23). 승인본은 Version 102이고, 찍을 때 읽은 게시본은 1795409939-0bad다.
- **구현:** `tests/agentMobileBoards.spec.ts`와 `tests/agentPanel.spec.ts`가 가짜 API(`VITE_API_MOCK=true`)로 각 상태를 띄워 찍었다. 모델은 부르지 않았다. 답변 문구는 합성 문구다.
- **다시 만들기:** `frontend`에서 `$env:AGENT_SHOT_DIR='<폴더>'; npx playwright test tests/agentMobileBoards.spec.ts tests/agentPanel.spec.ts`
- **노트 근거 기간:** 캔버스는 위키 문구이고, 구현은 디자인 v0.2 14.5의 노트 근거 기간 문구를 쓴다. 근거 없음(F6-12bm)의 두 번째 문장은 문장 A다.
- **F6-17m:** 보드처럼 앞 답변이 있는 대화에서 사용 제한이 온 경우를 찍었다(`F6-17m-after`).
- **F6-16m:** 그림 실패 카드는 PC와 같은 부품이라 그림 자리(답변 상자 안)에 있다. 보드는 답변 상자 위에 둔다(MEG-258 PR #194 결정 요청 1과 같은 차이).
