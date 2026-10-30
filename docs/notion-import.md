# Notion 가져오기

운영자가 로컬에서 실행하는 일회성 명령이다. 웹 API나 동기화 작업이 아니다.
선택한 데이터 소스의 체크된 페이지 본문을 `notes`와 `note_images`에 넣고 과목을 연결한다.
실제 노트·키·서명 URL을 파일, 콘솔, 저장소에 남기지 않는다. 시험은 합성 데이터만 사용한다.

## 규칙 체크리스트

- [x] 체크박스 서버 필터 + 응답의 체크 여부·부모 데이터 소스·휴지통 여부 재검사.
- [x] 선택된 페이지 본문 블록만 읽는다. 하위 페이지·DB·첨부·동기화 블록·링크 대상은 따라가지 않는다.
- [x] 제목·본문·공부일·과목을 가져온다. 이해도·공부 시간 및 그 밖의 속성은 복사하지 않는다.
- [x] 날짜 속성이 비었으면 생성일을 KST 날짜로 바꾼다. 최초 노트는 비공개다.
- [x] 기존 노트는 제목·본문·공개 여부를 포함해 수정하지 않는다. 없는 이미지 행만 보충한다.
- [x] DB 함수에서 노트와 과목(`subjects`, `note_subjects`)을 한 트랜잭션에 저장한다. 중간 실패 시 노트까지 롤백한다. 노트 고유 키 충돌은 기존 행을 반환하며, 이미지 복합 고유 키에는 `ignore-duplicates`를 적용한다.
- [x] 이미지 경로는 `notes/{note_id}/{notion_block_id}`. 업로드 후 행 기록에 실패하면 재실행 때 같은 경로를 덮어쓴다.
- [x] 본문 이미지는 `![설명](note-image:{notion_block_id})`. 서명 URL은 저장하지 않는다.
- [x] HTTPS·정확한 호스트·버킷 경로 검사, 모든 DNS 응답의 공개 IP 검사, 검증 IP로 접속 고정 및 원래 호스트로 TLS 인증서 검증.
- [x] 리다이렉트·프록시·압축 응답을 사용하지 않는다. 다운로드에는 서비스 키를 보내지 않는다.
- [x] 입력·재인코딩 출력 각 10,000,000바이트, 각 변 8,000px, 25,000,000화소 상한.
- [x] PNG·JPEG·WebP·GIF만 해독해 메타데이터 없는 PNG로 저장한다. GIF 등 애니메이션은 첫 프레임만 보존한다. SVG·알 수 없는 형식은 거부한다.
- [x] 시작할 때 버킷이 비공개인지 확인하며 버킷을 만들거나 설정을 바꾸지 않는다.

## 준비

`backend/`에서 `uv sync`를 실행한다. 개발 의존성에 이미지 처리 그룹이 포함된다.
개발 도구 없이 실행하려면 `uv sync --no-dev --group importer`를 사용한다.

운영자는 대상 프로젝트의 API Keys 화면에서 **가져오기 전용 secret key**를 별도로 발급할 수 있는지 확인하고 발급한다.
앱 키를 재사용하지 않는다. 별도 발급이 불가능하면 실행을 멈추고 결정을 다시 확인한다.
코드는 전용 환경변수를 요구하고 앱 키가 같은 환경에 있으면 값이 같은지 검사하지만,
그 키가 실제로 별도 발급되었는지 증명할 수는 없다.

아래 값은 현재 프로세스의 환경변수로만 설정한다. `.env`, 프로필, 명령 기록, 채팅에 키를 적지 않는다.
PowerShell에서 키 입력은 `Read-Host -MaskInput`으로 받아 환경변수에 할당할 수 있다.

| 환경변수 | 값 |
|---|---|
| `NOTION_IMPORT_TOKEN` | 대상 데이터 소스 읽기 권한만 있는 Notion 통합 토큰 |
| `NOTION_IMPORT_DATA_SOURCE_ID` | 데이터베이스 ID가 아닌 데이터 소스 UUID |
| `NOTION_IMPORT_CHECKBOX` | 운영자가 확인한 가져오기 체크박스 속성 이름 |
| `NOTION_IMPORT_DATE_PROPERTY` | 날짜 속성 이름(필수). 해당 페이지의 값이 비었을 때만 생성일(KST)을 사용 |
| `NOTION_IMPORT_SUBJECTS_PROPERTY` | 과목 다중 선택 속성 이름(필수). 선택값이 비어 있으면 과목 없이 저장 |
| `NOTION_IMPORT_SUPABASE_URL` | 대상 프로젝트 HTTPS 루트 URL |
| `NOTION_IMPORT_SUPABASE_SECRET_KEY` | 별도 발급한 `sb_secret_` 키 |
| `NOTION_IMPORT_BUCKET` | 운영자가 준비한 비공개 노트 이미지 버킷 이름 |

외부 DB 이름·속성 이름·원본 URL은 공개 문서에 넣지 않는다. 실제 매핑은 접근이 제한된 작업 기록을 따른다.
사람이 PR을 병합하고 `notion_import_subjects` 마이그레이션을 적용한 뒤 실행한다.
DB 함수 `import_notion_note`는 `service_role`만 실행 가능하며 기존 노트·과목 연결을 변경하지 않는다.
과목은 이름으로 중복을 제거해 연결한다. 한 페이지당 과목 최대 100개, 이름 1~100자다.
버킷 준비도 끝나 있어야 한다. 앱과 가져오기를 동시에 편집·삭제하지 말고 명령은 한 번에 하나만 실행한다.

## 실행과 결과

```console
cd backend
uv run --no-sync python -m scripts.import_notion
```

출력은 JSON 숫자 집계 하나다. 노트 본문·제목·페이지 ID·URL·응답 본문·예외 메시지는 출력하지 않는다.

| 항목 | 의미 |
|---|---|
| `notes`, `images` | 이번 실행에서 추가된 행 수 |
| `skipped_pages`, `skipped_images` | 선택되지 않았거나 이미 존재해 건너뛴 수 |
| `skipped_blocks` | 제외하거나 지원하지 않는 블록 수 |
| `rejected_images` | URL·형식·크기 보안 규칙으로 거부한 이미지 수 |
| `failed_pages`, `failed_images`, `fatal_errors` | 처리 실패 수, 전체 조회/설정/중단 오류 수 |

종료 코드 0은 실패·이미지 거부가 없다는 뜻이다. 제외 블록이 없다는 뜻은 아니므로 `skipped_blocks`도 확인한다.
1이면 일부 결과가 이미 저장되었을 수 있다. 설정·권한·네트워크를 확인하고 같은 명령을 다시 실행한다.
이전 노트는 유지하며 빠진 이미지 행을 채운다. 완료 후 재실행은 `notes=0`, `images=0`이어야 한다.
이미지 행이 있지만 Storage 객체만 사라진 경우에는 복구하지 않는다(복구 모드는 별도 범위).

가져오기 결과를 검토한 뒤 노트 공개 여부는 앱에서 별도로 정한다.
가져온 직후 이미지 파일 백업은 별도 백업 절차를 따른다. 이 명령은 백업 파일을 만들지 않는다.
작업 종료 후 Notion 통합 공유를 해제하고 Notion·Supabase 가져오기 전용 키를 폐기한다.
프로세스 환경변수도 제거한다. 재개에 필요한 키는 새로 발급한다.

## 지원 범위와 검증 한계

문단·제목·목록·체크 항목·인용·콜아웃·코드·수식·표·토글·열·이미지를 변환한다.
굵게·기울임·취소선·인라인 코드·HTTP(S) 링크를 보존하며 링크는 읽으러 가지 않는다.
토글은 굵은 제목과 들여쓴 목록, 표는 Markdown 표다. 원본 화면 배치·색·밑줄은 보존하지 않는다.
본문이 200,000자를 넘거나 깊이 32·블록 10,000개를 넘으면 페이지를 실패로 센다.

이미지 허용 목록은 공식 문서에서 확인한 `s3.us-west-2.amazonaws.com`의 `/secure.notion-static.com/` 경로로 제한한다.
다른 Notion 파일 호스트 및 외부 이미지도 현재는 거부한다. 새 호스트가 필요하면 공식 근거를 확인하고 코드·보안 테스트를 함께 검토해야 한다.
문서 예시는 전체 호스트 목록을 보장하지 않는다. 실제 노트의 이미지 호스트 적합성은 아직 검증하지 않았다.

단위 시험은 HTTP 모의 응답과 메모리 이미지로 수행한다. SQL 통합 시험은 포트가 노출되지 않은
별도 PostgreSQL 17 컨테이너에서 전체 마이그레이션을 적용하고 중복·과목 연결·원자성·권한을 확인한다.
이 시험의 `auth.users`는 FK 검증용 최소 테이블이므로 실제 Supabase Auth 시험은 아니다.
실제 Notion 연결, 해당 프로젝트의 별도 키 발급,
Supabase REST·Storage 왕복, 실제 노트 변환 품질은 운영자 실행 전 별도 확인 사항이다.
원격 DB에는 자동 적용하지 않는다. 기존 테이블 권한과 RLS를 바꾸지 않는다.

## 공식 자료 (2026-10-30 확인)

- [Notion 파일 객체](https://developers.notion.com/reference/file-object): 파일 타입, 호스트·버킷 예시, 임시 URL 만료.
- [Notion 파일 읽기](https://developers.notion.com/guides/data-apis/retrieving-files): 블록 읽기와 API 버전 `2026-03-11`.
- [데이터 소스 쿼리](https://developers.notion.com/reference/query-a-data-source): 체크박스 필터와 커서 페이지 처리.
- [Supabase API 키](https://supabase.com/docs/guides/getting-started/api-keys): 컴포넌트별 secret key와 `apikey` 헤더.

```console
uv run --no-sync pytest tests/test_import_notion.py -q
```

SQL 통합 시험은 운영 DB 접속 문자열을 받지 않는다. 개발자가 `--network none`인 일회용
`postgres:17` 컨테이너를 준비하고 그 이름을 `NOTION_IMPORT_TEST_CONTAINER` 환경변수에 넣은 뒤
`uv run --no-sync pytest tests/integration/test_notion_import_sql.py -q`를 실행한다.
테스트가 전용 임시 DB를 생성하고 삭제한다. 컨테이너가 지정되지 않으면 건너뛴다.
컨테이너는 시험이 끝난 뒤 준비한 개발자가 제거한다.
