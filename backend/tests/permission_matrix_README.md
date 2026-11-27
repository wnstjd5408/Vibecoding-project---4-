# 권한 행렬 시험 (MEG-69)

API spec v0.2 2·4절과 기술 검토 v0.2 3·8절의 공개 가능한 권한 계약을
`permission_matrix.py`에 적었다. 실제 `app.main.app`의 라우터·세션·역할 검사와
로컬 Supabase Auth·REST·RPC·Storage를 함께 실행한다.

## 실행

Docker Desktop과 저장소의 Python 환경이 필요하다. 다른 세션과 공유하지 않는
전용 worktree에서 실행한다. 포트는 사용 중인 포트와 겹치지 않게 고른다.
아래 명령의 작업 디렉터리는 `backend/`다.

```powershell
uv sync --frozen
uv run python -m scripts.local_backend prepare --base-port 58320
# 기존 local_backend start는 Storage를 제외하므로 이 시험은 Storage도 시작한다.
# CLI 출력에는 로컬 자격증명이 있으므로 helper가 출력을 수집하고 표시하지 않는다.
uv run python -c "from scripts.local_backend import cli; cli('start', '-x', 'realtime,imgproxy,mailpit,postgres-meta,studio,edge-runtime,logflare,vector,supavisor'); print('Local Auth/REST/Storage ready')"
$env:MEG69_LOCAL='1'
uv run pytest tests/permission_matrix_local.py -v -rs --tb=short
Remove-Item Env:MEG69_LOCAL
uv run python -m scripts.local_backend stop
```

`prepare`는 최초 한 번만 실행한다. 이 worktree의 `.local-backend` 구성과 프로젝트
식별자를 대조하고 리터럴 루프백 주소만 허용한다. 원격 URL·키를 입력받지 않는다.
로컬 CLI에서 읽은 키와 실행 중 생성한 비밀번호는 메모리에만 둔다.
상속된 `SUPABASE_URL`이 다른 환경이면 기존 helper가 실행을 거부한다.

이 시험은 전용 로컬 프로젝트의 rate-limit 카운터를 케이스마다 비운다.
제품 limiter와 SQL 함수 자체는 그대로 호출한다. 사용자와 버킷은 실행할 때 만들고
끝날 때 지운다. 합성 노트·용어·문항 등의 예약 ID가 이미 있으면 덮어쓰지 않고 실패한다.
강제 종료로 데이터가 남았다면 해당 전용 프로젝트를 정리한 뒤 다시 실행한다.
공유 개발 DB나 다른 worktree의 로컬 스택으로 실행하지 않는다.

## 검증 범위

- 기본 행렬: 26개 엔드포인트 × 방문자·일반 사용자·운영자 = 78개 조합.
- 세션 상실: 인증 필요 API 및 E03·E07을 만료·비활성 세션으로 호출한다.
  만료는 액세스 쿠키 수명 종료 후, 실제 서명된 리프레시 쿠키의 앱 최대 수명이 지난 경우다.
  비활성은 매 케이스 새로 발급한 실제 Auth 세션과 `profiles.is_active=false`로 검증한다.
- 비공개 노트: E05의 404·이미지 서명 차단, E09의 읽기 권한을 역할별로 확인한다.
- 객체 소유권: 일반 사용자와 운영자 모두 남의 문항에 대한 E10·E12·E13·E14는 404다.
- Origin: 상태 변경 API마다 누락·다른 출처를 각각 `403 origin_not_allowed`로 확인한다.
  기본 행렬은 항상 허용 Origin과 유효한 입력을 사용한다.
- 거부·무기록: 제품 테이블 전체 행 값, Auth 사용자 ID, Storage 객체 메타데이터의 전후 해시를
  비교하고 HTTP 쓰기 시도도 검사한다. rate-limit 카운터와 인증 갱신·비활성 세션 회수는
  의도된 제어 동작이라 제품 데이터 불변 검사에서 제외한다.

E09는 합성 AI 설명 캐시, E11은 합성 ready 세트, E13은 저장된 미답변 꼬리 질문으로
성공 경로를 확인한다. 퀴즈 업무 시계만 고정하며 Auth·세션 시계는 실제 시간을 쓴다.
AI 생성 단계 진입은 즉시 시험 실패로 막는다. 외부 AI 생성 품질·비용 정산을 검증한 것으로
보고하지 않는다. 화면·배포 검증도 이 시험의 범위 밖이다.

## 건너뜀과 결과 해석

MEG-79 병합 후 E01~E26 전체를 활성화했다. E15는 비공개 노트와 이미지 URL,
E16은 실제 생성된 노트, E17은 비공개→공개 전환 및 방문자 읽기,
E18은 노트·이미지 행·Storage 객체 삭제까지 확인한다.

`test_permission_matrix_inventory.py`는 외부 환경 없이 기본 CI에서 실행된다.
구현된 경로가 사라지면 실패한다. 경로 부재를 자동으로 건너뛰지 않는다.

기본 pytest는 `test_*.py`만 수집하므로 로컬 행렬 파일은 위 명령처럼 명시적으로 실행한다.
기존 CI의 필수 시험 무건너뜀 정책은 그대로 유지한다. 로컬 파일을 명시했더라도
`MEG69_LOCAL`이 없으면 실제 통합 시험은 전부 건너뛴다. 기본 pytest/CI 통과만으로 권한
AC를 충족했다고 판단하지 않는다. PR에는 기본 78개 조합과 보강 케이스의 통과·실패·건너뜀
수를 구분하고 기준 커밋을 기록한다.

## CS Agent 권한(AG09, MEG-282)

`agent_permission_local.py`는 같은 전용 로컬 스택과 `LocalMatrix`로 CS Agent 경로(E27~E32)를 본다.
PRD v0.5 AG09 "타 사용자 대화·미공개 근거·권한 회수 자료를 노출하지 않음"과 API spec v0.2 8절이 기준이다.
위 실행 순서에서 마지막 pytest만 바꿔 실행한다.

```powershell
$env:MEG69_LOCAL='1'
uv run pytest tests/agent_permission_local.py -v -rs --tb=short
Remove-Item Env:MEG69_LOCAL
```

- 다른 사용자: 운영자↔일반 사용자 양방향으로 남의 대화·턴·출처가 E28·E29·E30·E31·E32에서 모두 404이고,
  남의 실행 중 턴은 그대로 running이다.
- 비공개·없는 노트: 일반 사용자의 E27이 404다(공개 노트 대조군은 201).
- 회수: 운영자가 실제 E17(비공개)·E18(삭제)로 바꾼 뒤 확인한다.
  - 대화 노트·선택 문맥 노트를 회수하면 그 대화의 모든 경로가 404다. 삭제는 대화·턴이 외래키 연쇄로 사라진다.
  - 인용한 노트를 회수하면 일반 사용자·운영자 모두 E28·E30에서 그 턴과 뒤 턴이 `hidden`(source_revoked)이고,
    응답에 결과·출처 제목·인용 문단이 없으며 E32는 404다.
- 지운 대화: 모든 경로가 404다.
- 검색: E29가 쓰는 `NoteRetriever`가 역할과 관계없이 실제 DB에서 공개 노트만 읽는다.
- 거부 경로는 CS Agent 테이블과 원장까지 포함한 전체 행 값 해시가 전후로 같고, 쓰기 요청이 없어야 한다.

- 같은 키 재전송(E29 재생): 회수된 인용은 재생 응답도 `hidden`이고, 대화 노트를 회수하면 404이며, 남이 주인의 키로 보내도 404다.
- 비활성 계정은 자기 옛 대화도 401이다. E29는 대화의 노트가 아닌 노트의 선택 문맥을 422로 거절한다(Q17).
  그래서 선택 문맥 노트를 지우는 일은 대화 노트를 지우는 일과 같다.
- 대조군으로 주인의 읽기·재생·E29 409(`turn_in_progress`)·E31 중단을 확인한다. 모르는 경로도 404라서 거부만으로는 경로를 구분하지 못한다.

전후 해시가 테이블 전체를 보므로 같은 로컬 DB를 쓰는 다른 시험·프로세스와 동시에 실행하지 않는다.
대화·턴·출처 행은 SQL로 넣는다. 노출 중단·위키 플래그는 끈 상태로 본다. 예산·설정은 읽지만
모델 클라이언트와 검색은 부르면 실패하므로 E29 성공 경로(답 생성)·스트림 재생·위키 출처는 이 시험의 범위 밖이다.
