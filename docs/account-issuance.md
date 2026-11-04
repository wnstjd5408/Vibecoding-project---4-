# 계정 발급 실패 확인

`POST /api/admin/users`는 Auth 생성 요청마다 서버에서 새 UUID를 정한다. 브라우저는 ID를 지정할 수 없다. Auth 성공 뒤 `profiles` 저장이 실패하면 그 사용자만 삭제하고 500을 반환한다.

Auth 응답이 유실되거나 성공 본문을 확인할 수 없으면 `503 service_unavailable`을 반환하고, 미리 정한 UUID로 삭제를 시도한다. 계정 생성 POST를 자동 재시도하지 않는다. 삭제에 성공하면 운영자가 다시 발급할 수 있다.

## 생성 결과가 불확실할 때

`creation_uncertain` 로그에는 요청 ID와 이 시도에 할당한 Auth 사용자 ID가 남는다. 삭제도 확인하지 못하면 같은 ID로 `cleanup_unconfirmed`가 남는다. 이메일·비밀번호·외부 오류 본문은 로그에 넣지 않는다.

운영자는 해당 요청 ID의 Auth 작업이 끝난 뒤 대시보드에서 기록된 사용자 ID를 확인한다. 그 ID가 남아 있고 앱 프로필이 없다면 수동 삭제한 후 재발급한다. 이메일이 같다는 이유로 다른 ID의 기존 사용자를 삭제하지 않는다. 프로필이 있다면 바로 삭제하지 말고 해당 요청의 결과를 먼저 확인한다.

삭제 요청의 404만으로 생성되지 않았다고 확정하지 않는다. 원래 생성 요청이 뒤늦게 커밋될 수 있기 때문이다. 이 경우도 기록된 ID로 확인해야 한다. 네트워크 단절·프로세스 종료까지 포함한 자동 원자성이나 무조건적인 자동 복구를 보장하지 않는다.

## 속도 제한

Auth가 429를 반환하면 API도 `429 rate_limited`와 `Retry-After`, `retry_after_seconds`를 반환한다. 초와 HTTP-date 형식을 처리하며, 헤더가 없거나 해석할 수 없으면 안내값 60초를 사용한다. 서버가 내부적으로 생성 요청을 재시도하지 않는다.

## 회귀 시험

- `uv run pytest -q tests/test_account_issuance.py`: 실제 HTTP 어댑터에 커밋 후 타임아웃·5xx·잘못된 성공 본문·삭제 실패·429를 주입한다.
- 격리된 로컬 Supabase에 `MEG67_TEST_SUPABASE_URL`, `MEG67_TEST_SUPABASE_KEY`를 설정한 뒤 `uv run pytest -q tests/test_account_issuance_local.py`를 실행한다. 실제 생성 성공 응답을 버리는 시험과 삭제 후 재발급·로그인 시험을 포함한다. 원격 주소는 거부한다.
