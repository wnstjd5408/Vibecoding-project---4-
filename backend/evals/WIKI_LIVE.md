# 위키 개발 사례 live 평가

승인된 개발 manifest를 Bedrock에 보내는 로컬 전용 실행기다.
기존 staging API와 최종 골든 평가 경로는 변경하지 않는다.
DB·검색은 연결하지 않고 승인된 합성 근거를 사용한다.

## 입력과 승인

cases.json과 manifest.json을 저장소 밖 비공개 경로에 둔다.
make_plan은 원문·용어·근거만 허용 목록으로 전달하며, 참조 정답과
평가 기준·승인 상태는 요청에서 제외한다. 근거는 숫자 인용 ID로 변환하고
원래 ID·URL과의 연결은 로컬에서 유지한다.

initialize는 승인 ID, 실행 ID, 예산, live/mock 구분, 요청/데이터 해시,
고정된 파일 원장 경로를 묶는다. 기존 파일을 덮어쓰지 않는다.
승인 파일 자체는 사용자 승인의 대체물이 아니다. 실행 담당자는 사용자의
승인 범위를 확인한 뒤 한 번만 초기화해야 한다.

원장 파일과 승인은 한 머신의 같은 비공개 경로에서만 사용한다.
복사본을 별도 실행하거나 원장을 삭제해 재승인하는 것은 지원하지 않는다.
파일 원장은 로컬 운영자에 대한 변조 방지 저장소나 분산 원장이 아니다.
여러 호스트/서버리스 실행에는 이 경로를 사용하지 않는다.

## 실행 순서

backend 작업 위치에서:

    uv run --with 'botocore[crt]' python -m evals.wiki_live <private-bundle> <approval.json> --phase canary --profile <aws-profile>
    uv run --with 'botocore[crt]' python -m evals.wiki_live <private-bundle> <approval.json> --phase remaining --profile <aws-profile>

AWS CLI login 프로필은 Python SDK에 CRT 의존성이 필요할 수 있다.
위 명령은 별도 uv 실행 환경에 이를 제공한다. 인증 준비 실패는 요청 전에
발생할 수 있으므로 실제 원장의 attempts를 확인하며 호출 여부를 추정하지 않는다.
잠금은 승인 디렉터리 공통 .wiki-live.lock으로 여러 승인 파일의 경합도 막는다.

첫 단계는 첫 사례 하나만 호출한다. 출력 형식·인용·사용량·종료 상태를
확인한 뒤 남은 단계로 진행한다. SDK 자동 재시도는 끈다.
출력 부족/오류/불명확한 응답은 추가 호출을 중단하고 기록을 조사한다.
강제 종료 시 started 또는 남은 잠금이 확인되면 임의 삭제/재실행하지 않는다.
성공한 사례는 재호출하지 않는다. 오류를 해결한 뒤의 새 시도는 별도 승인 대상이다.

CountTokens 추정 대신 기존 Luna 서비스 문맥 한도의 보수적 비용 예약을
사용한다. 바이트 제한은 요청 크기 제한이며 토큰 상한 증명이 아니다.
실제 usage의 입력·출력·캐시 항목을 저장하고 추정 요금과 AWS 청구를 구분한다.
비용 정책의 모델·지역·서비스 등급이 바뀌면 호출 전에 재검토한다.

## 출력과 검수

한국어 3줄 요약과 정의·작동 원리·활용 예시·주의사항을 가진 explanation,
숫자 source_ids를 검사한다. URL은 모델이 생성하지 않고 서버측 근거에서
해결한다. 기계적 검사는 사실성·읽기 쉬움의 판정이 아니다.

wiki_live_review.templates/aggregate는 실제 run·approval·output 해시에
검수 양식을 묶는다. AI 검수 초안과 사용자 승인 결과는 별도다.
human_approved가 false이면 정식 결과는 pending을 유지한다.
새 출력이나 다른 실행에 예전 검수 결과를 재사용하면 거부한다.
6개 개발 사례 결과로 봉인된 골든 통과나 제품 정확도를 주장하지 않는다.

실제 출력·원장·사용량·검수 기록은 비공개 경로에 보관한다.
공개 PR에는 합성 테스트와 공개 가능한 검증 요약만 포함한다.
