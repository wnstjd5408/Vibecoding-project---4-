# AI 호출 인증과 Bedrock API 키 운영

백엔드가 Amazon Bedrock을 부를 때 쓰는 인증 방식과, 대체 경로인 장기 API 키의 발급·교체·정리 절차다. 코드는 `backend/app/bedrock.py`다. 계정 ID·역할 ARN·키 값은 이 문서에 적지 않는다.

## 방식

| `AI_AUTH_MODE` | 동작 | 언제 쓰나 |
|---|---|---|
| `oidc` (기본) | 요청의 Vercel OIDC 토큰을 STS 임시 자격증명으로 바꿔 SigV4로 서명한다. 필요한 값: `AWS_ROLE_ARN` | 평소 |
| `api_key` | 환경변수 `AWS_BEARER_TOKEN_BEDROCK`의 장기 API 키를 Bearer로 보낸다 | OIDC가 막혔을 때만 |

두 방식의 호출 코드와 결과 형식은 같다. 장기 키는 AWS가 탐색용으로 안내하므로 대체 경로로만 둔다. 키를 켜 두는 기간이 길수록 노출 위험이 커진다.

## 키 규칙

- 만료는 **30일**로 발급한다. 상한 90일은 IAM 조건 `iam:ServiceSpecificCredentialAgeDays`로 건다. 최소 만료는 1일이다.
- 키는 IAM 사용자 하나에 묶인다. 사용자당 최대 2개가 동시에 활성이어서 교체 때 겹쳐 쓸 수 있다.
- 권한은 `AmazonBedrockLimitedAccess` 대신 인라인 정책으로 좁힌다. `bedrock:InvokeModel`(추론 프로필·리전 모델·글로벌 모델 3문장, 조건 `aws:RequestedRegion`·`bedrock:InferenceProfileArn`)과 `bedrock:CallWithBearerToken`이 필요하다. 뒤의 것을 빼면 `AccessDeniedException`이 난다(2026-10-22 시험).
- 장기 키는 만든 리전에서만 쓸 수 있다. 호출 리전과 같은 리전에서 만든다.
- 키 값은 화면·로그·이슈·PR에 쓰지 않는다. 환경변수(로컬은 git이 무시하는 `backend/.env`, 배포는 Vercel 환경변수)로만 둔다.

## 발급

1. IAM 사용자와 인라인 정책을 만든다. 정책은 위 규칙의 4문장이다.
2. 키를 만든다. 응답에 키 값이 한 번만 나오므로 화면에 출력하지 말고 파일로 받는다.
   ```powershell
   aws iam create-service-specific-credential --user-name <사용자> --service-name bedrock.amazonaws.com --credential-age-days 30 --region <리전> --output json | Out-File -Encoding ascii "$env:TEMP\bedrock-key.json"
   ```
3. 파일의 응답 필드 중 `ServiceCredentialSecret`이 키 값이다. 환경변수에 옮기고 임시 파일을 지운다.
4. 합성 텍스트로 호출해 `pong` 같은 짧은 응답이 오는지 확인한다.

## 교체 (겹침 7일)

1. 만료 7일 전에 새 키를 발급한다. 옛 키는 그대로 둔다.
2. 앱의 환경변수를 새 키로 바꾸고 배포한 뒤 호출이 되는지 확인한다.
3. 겹침 7일 동안 옛 키를 `Inactive`로 두고 문제가 없는지 본다. 문제가 생기면 `Active`로 되돌린다.
   ```
   aws iam update-service-specific-credential --user-name <사용자> --service-specific-credential-id <ID> --status Inactive
   ```
4. 문제가 없으면 옛 키를 삭제한다.
   ```
   aws iam delete-service-specific-credential --user-name <사용자> --service-specific-credential-id <ID>
   ```
5. 유출이 의심되면 만료 전 키는 `reset-service-specific-credential`로 새 값을 받는다. 이미 만료됐으면 삭제하고 새로 만든다.

만료 알림 기능은 없다. 만료일은 `list-service-specific-credentials`의 `ExpirationDate`로 확인하고 일정에 적어 둔다.

## 대체 경로를 끌 때

키(`Inactive` 후 삭제), 인라인 정책, IAM 사용자를 이 순서로 지우고 환경변수의 키를 비운다.

## 알려진 함정

- `AWS_BEARER_TOKEN_BEDROCK`이 환경에 있으면 boto3는 SigV4 자격증명을 명시해도 Bearer를 우선한다. `oidc` 모드는 코드에서 서명 방식을 `v4`로 고정해 이 영향을 막는다(테스트로 확인).
- `.env.example`의 빈 값은 설정하지 않은 것으로 본다.

## 확인하지 않은 것

- 만료된 키가 어떤 오류 코드로 실패하는지. 최소 만료가 1일이라 시험하지 못했다. 무효(가짜) 키는 `AccessDeniedException`이다.
- 발급한 키의 만료일을 나중에 바꾸는 방법(문서에서 찾지 못했다).
- 회사 계정 정책(SCP)이 장기 키 생성을 막는 경우의 동작. 이번 계정에서는 막지 않았다.
