# MEG-113 목업 v0.2 구현 검토

`npm ci` 후 `npm run dev`로 실행하고 `/dev/mockup`을 연다. 기존 공통 기반 화면의 개발용 링크에서도 진입할 수 있다. 31개 원본 프레임의 이름·상태·뷰포트 대응은 `src/mockup/screens.ts`에 있으며 `/dev/mockup/F1-1`처럼 직접 열 수 있다. `?clean=true`는 검토 이동 링크를 숨기고 `?theme=dark`는 어두운 테마를 적용한다.

## 구현 범위

노트 목록·검색·과목 필터, 노트 읽기, 용어 시트·전체 화면, AI 설명 상태, 즐겨찾기, 로그인 안내·합성 로그인, 퀴즈·해설·꼬리 질문, 계정 메뉴·정보, 운영자 노트 생성·수정·삭제, 용어 편집·이미지 미리보기, 계정 발급 결과, 신고 필터·해결·용어 정정을 제공한다.

React Router와 기존 프런트 기반에 별도 지연 로딩 경로로 연결했다. 공통 Button, IconButton, Field, Card, Badge, Dialog 및 scoped CSS Modules를 사용한다. 실제 제품 경로는 기존 구현을 유지한다. 데이터는 PreviewProvider 메모리에만 있으며 새로고침하면 초기화된다. 실제 인증·계정 발급·AI 호출·DB 저장·이미지 업로드·배포는 포함하지 않는다. 로그인 예시는 화면 카탈로그에 표시된 합성 계정만 사용한다.

## AC별 검증

| AC | 결과 및 근거 |
|---|---|
| AC-1. 목업 31개 화면·상태가 접근 가능하며 원본 대응 목록이 있다. | screens.ts의 31개 프레임과 개별 URL을 Chromium에서 모두 확인. 각 프레임의 제목, h1, 폰트 로딩, 가로 넘침, 콘솔 오류를 검사하고 스크린샷을 생성한다. |
| AC-2. 주요 사용자·운영자 목업 흐름을 이동·조작할 수 있다. | 11개 흐름 테스트로 필터, 용어·로그인 시트, 합성 로그인, 퀴즈, 즐겨찾기, 노트 CRUD, 용어 저장, 계정 결과, 신고 정정·해결, 좁은 화면을 확인. |
| AC-3. lint·build 및 필요한 동작 검증이 통과한다. | npm run lint, npm run build, npm run test:e2e 통과. Playwright Chromium 42개 테스트. |
| AC-4. 시각 검증 결과와 미검증·제한 사항을 리뷰 자료에 남긴다. | 아래 원본 비교 방법 및 한계와 tests/mockup.spec.ts의 스크린샷 첨부를 제공. |

## 시각 비교 및 한계

제공된 HTML export의 JSON/gzip 템플릿에서 HTML/CSS를 읽었다. `scripts/capture-design.mjs`는 내장 실행 스크립트를 제거하고 export 전용 SVG·테이블 태그를 표준 태그로 정규화해 원본 31개 프레임을 캡처한다. 외부 요청은 차단하고 로컬 폰트만 사용한다. 라이브 Claude 화면을 직접 캡처한 결과는 아니다.

목록, 용어 시트, 로그인, 퀴즈, 운영자 목록·용어 편집의 대표 화면을 원본 캡처와 육안 비교했다. 원본 색·간격·반경·SVG를 사용하고 헤더·표·폼 정렬을 보정했다. 픽셀 단위 동일성이나 모든 상태의 완전한 시각 일치는 보장하지 않는다. 동작 연결을 위한 합성 내용, 시트 뒤 배경 본문, 일부 폼 간격 및 브라우저 기본 파일 선택 UI에는 차이가 남을 수 있다. 기존 디자인 승인과 별개로 PR에서 구현 결과를 확인한다.

원본이 참조한 폰트 바이너리는 export에 포함되지 않아 공식 Pretendard v1.3.9 배포 파일과 OFL 라이선스를 `public/fonts`에 포함했다. 원본 폰트와 해시 일치 및 별도 디자인 시스템 v5와 토큰 일치는 확인하지 않았다. Safari/Firefox, 실제 모바일 터치·스크린리더, 실제 서버 연동은 미검증이다.

## 재현

```sh
npm ci
npx playwright install chromium
npm run lint
npm run build
npm run test:e2e
npx playwright show-report
```

테스트는 포트 4183의 전용 Vite 서버를 띄운다. `playwright-report`에 각 화면 스크린샷·실패 trace가 첨부되며 산출물은 git에서 제외한다. 원본 HTML을 보유한 경우 아래 명령으로 별도 원본 캡처를 생성할 수 있다. 원본 HTML 및 추출 파일은 저장소에 포함하지 않는다.

```sh
node scripts/capture-design.mjs "<local-export.html>" "<output-directory>"
```

대표 구현 스크린샷은 `screens/`에 보관한다. CI의 PR 메타데이터 검사는 이 동작·시각 검증을 대체하지 않는다.
