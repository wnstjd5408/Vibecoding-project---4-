# MEG-259 'AI에게 질문' 진입점과 노출 중단: 검증 스크린샷

`screens/`의 이미지는 노출 중단 플래그(`VITE_CS_AGENT_DISABLED`)를 켠 빌드와 끈 빌드의 화면이다. 모두 가짜 API(`VITE_API_MOCK=true`)로 찍었고 모델은 부르지 않았다.

| 파일 | 빌드 | 화면 |
|---|---|---|
| `on-pc-select.png`, `on-mobile-select.png` | 플래그 켬(개발 서버) | 노트 글자를 고르면 'AI 설명'만 보인다 |
| `on-pc-explain.png`, `on-mobile-explain.png` | 플래그 켬(개발 서버) | 'AI 설명'(E09)이 지금처럼 열린다(AC-3) |
| `on-login.png` | 플래그 켬(개발 서버) | 방문자 로그인 안내. 본문에 'AI에게 질문'이 없다 |
| `off-pc-select.png`, `off-mobile-select.png` | 플래그 끔(개발 서버) | 노트 글자를 고르면 'AI에게 질문'만 보인다(AC-1) |
| `off-login.png` | 플래그 끔(개발 서버) | 방문자 로그인 안내. 캔버스 F2-2b 문구다 |
| `503-pc-first.png`, `503-mobile-first.png` | 플래그 끔(개발 서버) | 첫 질문이 503이면 질문은 남고 새 질문 입구가 닫힌다(AC-2) |
| `503-pc-followup.png` | 플래그 끔(개발 서버) | 답변 뒤 다음 질문이 503이어도 앞 답변과 출처는 계속 읽는다(AC-2) |
| `build-off-pc-select.png`, `build-off-pc-answer.png`, `build-off-login.png` | 플래그 끔(제품 빌드, `vite build` + `vite preview`) | 제품 빌드에서도 'AI에게 질문'이 열리고 답변을 받는다 |

**다시 만들기:** `frontend`에서 아래 명령을 실행하면 개발 서버 스크린샷이 `<폴더>/<파일 이름>.png`로 저장된다. 제품 빌드 스크린샷은 임시 설정으로 찍었고 저장소에 남기지 않았다.

```powershell
$env:ENTRY_SHOT_DIR='<폴더>'; npx playwright test tests/agentEntry.spec.ts tests/agentDisabled.spec.ts
```

**임시 문구:** 503 카드와 입력 칸 자리의 안내(`src/agent/messages.ts`의 `unavailable`·`unavailableHelp`·`closedNotice`)는 캔버스에 보드가 없는 임시 문구다.
