# MEG-254 위키 출처 보기와 위키 질문 입구: 리뷰 스크린샷

`screens/`의 이미지는 `tests/agentWiki.spec.ts`가 가짜 API(`VITE_API_MOCK=true`)로 찍었다. 모델은 부르지 않았고, 문구는 합성 문구다.

- **파일 이름:** `<Playwright 프로젝트>-<기기>-<상태>.png`
  - `agent-wiki`: 화면 위키 플래그를 켠 빌드(`VITE_CS_AGENT_WIKI_ENABLED=1`, 4187)
  - `agent-enabled`: 화면 위키 플래그를 끈 빌드(4185, 지금 운영 값과 같다)
- **상태:** `F6-4-wiki-source`(위키 출처 보기), `term-sheet-flag-on`·`term-sheet-flag-off`(위키 출처에서 연 용어 시트), `wiki-conversation`(위키 대화), `wiki-source-changed`(인용 뒤 바뀜), `wiki-ask-422`(화면 값만 켜진 배포)
- **목업과의 관계:** 캔버스에 위키 출처의 '용어 시트 열기'와 용어 시트의 'AI에게 질문' 보드는 없다. 문구와 동작은 MEG-254 결정 4(2026-11-23)의 임시안이다. 출처 보기 구조는 F6-4·F6-9를 따른다.
- **다시 만들기:** `frontend`에서 `$env:AGENT_SHOT_DIR='<폴더>'; npx playwright test tests/agentWiki.spec.ts`
