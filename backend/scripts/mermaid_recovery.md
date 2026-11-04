# Mermaid 복구 후 집계와 재개

`audit_mermaid_fences.py`의 `blocks_already_marked`는 저장 본문에 이미 표시된 Mermaid 블록 개수다. 모든 울타리가 Mermaid인 노트는 Notion 조회를 생략하지만 합계에는 포함한다. 따라서 이 숫자만으로 Notion 재검증을 완료했다고 판단하지 않는다.

`apply_mermaid_fences.ps1`은 사람이 검토한 외부 SQL 묶음을 실행하는 **쓰기 도구**다. 대조 스크립트 자체는 여전히 읽기 전용이다. PowerShell 7과 Docker가 필요하다. 자격증명은 `DATABASE_URL` 환경변수로 전달하고 원문·SQL은 저장소 밖 제한된 폴더에 둔다.

## 준비 파일 계약

`-SplitDir`에 다음 파일을 준비한다. 이 실행기는 SQL을 생성하거나 SQL의 안전성을 심사하지 않는다. 각 파일의 대상 환경·목록·원본 조건을 사람이 먼저 검토한다.

- `state-pilot.sql`, `state-rest.sql`: **읽기 전용 트랜잭션**에서 현재 본문을 확정 원본·적용본과 전체 문자열로 비교한다. 각 대상 ID를 오름차순으로 한 번씩 반환하며 출력 형식은 `id,original` 또는 `id,applied`다. 누락·다른 본문은 `id,missing` 또는 `id,drift`로 반환한다. 행 누락이나 다른 상태를 성공으로 취급하지 않는다.
- `1-pilot-apply.sql`, `2-rest-apply.sql`: 대상 그룹별 단일 트랜잭션. 원본 본문 일치 조건의 UPDATE가 한 행도 바꾸지 못하면 예외를 발생시킨다.
- `1-pilot-restore.sql`: 적용본 본문 일치 조건으로 파일럿 원본을 복구한다. 나머지 그룹이 적용된 경우 파일럿만 자동 복구하지 않는다. 전체 복구 SQL은 별도 검토·실행 대상이다.

상태 조회와 UPDATE 사이의 변경도 위 UPDATE 조건이 막아야 한다. 상태 조회 결과만 믿고 무조건 UPDATE하는 SQL을 사용하지 않는다. 실제 데이터에서 만든 SQL은 이 저장소에 포함하지 않는다.

## 사용 예시 (합성 ID)

```powershell
./scripts/apply_mermaid_fences.ps1 -SplitDir /restricted/audit/split `
  -PilotNoteId 1 -RestNoteIds 2,3 -ExpectedMarkedBlocks 4 `
  -NoteUrl https://example.invalid/notes/1
```

처음에는 원본인 그룹만 적용한다. 화면 확인에서 `k`를 선택하고 같은 명령을 재실행하면 파일럿이 적용본과 정확히 일치하는지 확인한 뒤 UPDATE 없이 화면 확인부터 재개한다. 전체 적용 후 재실행도 중복 UPDATE를 하지 않는다. 누락·본문 변경·그룹 내 부분 적용은 중단한다. `n`은 나머지가 원본일 때만 파일럿을 복구한다.

`-AuditBackend`의 기본값은 현재 스크립트의 상위 backend 폴더다. 재대조에는 `MERMAID_AUDIT_SUPABASE_URL`, `MERMAID_AUDIT_SUPABASE_SECRET_KEY`, `NOTION_IMPORT_TOKEN`이 필요하다. 이 환경이 DATABASE_URL과 같은 대상으로 설정됐는지 사람이 확인한다. 출력 디렉터리는 매번 새로 만든다. `-ExpectedMarkedBlocks`는 **재대조 전체 범위의 예상 합계**다. 다른 노트가 추가되어 합계가 바뀌면 자동 성공 처리하지 않고 검토한다.

`-SkipAudit` 또는 환경변수 누락 시 본문 일치만 확인하고 Notion 재대조 미실행을 표시한다. `-NoPause`는 질문을 자동 수락하므로 원격 환경에서 사용하지 않는다. 앱은 외부 SQL 변경을 자동 구독하지 않으므로 화면 확인 전에 새로고침한다.

## 검증 범위

`pytest tests/test_audit_mermaid_fences.py tests/test_mermaid_resume_runner.py -q` 또는 `pwsh -NoProfile -File tests/powershell/mermaid_resume.ps1`.

PowerShell 시험은 합성 상태와 가짜 Docker/uv 함수를 사용한다. 실제 DB, SQL 실행, 원격 권한·트리거, 운영 화면 검증을 대체하지 않는다. PowerShell이 없는 환경에서는 Python의 실행기 시험이 skip된다.
