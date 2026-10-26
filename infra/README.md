# infra — AWS 운영 설정

AWS 계정의 비용 경보, 감사 로그, 감사 이벤트 알림을 Terraform으로 관리한다(MEG-99). AI는 코드와 PR을 만들고 `init`·`plan`까지 실행할 수 있다. `apply`와 상태 버킷 생성, 시험 이벤트는 사람이 한다(2026-10-26 결정).

공개 저장소라서 계정 ID·이메일·예산 금액·버킷 이름은 커밋하지 않는다. 이 값은 `terraform.tfvars`와 `backend.hcl`에만 둔다. 두 파일은 `.gitignore`에 들어 있다. 상태 파일과 plan 파일에도 이 값이 평문으로 들어가므로 상태 버킷을 읽을 수 있는 사람은 비공개 값도 볼 수 있다.

## 관리하는 것

| 파일 | 리소스 | 리전 | 출처 |
|---|---|---|---|
| `budget.tf` | 월 예산 `cs-learning-monthly`와 경보 4개(실제 50·80·100%, 예상 100%), 비용 이상 탐지 모니터·구독 | 글로벌 | 콘솔에서 만든 것을 가져옴 |
| `cloudtrail.tf` | 트레일 `cs-learning-audit`, 로그 버킷과 공개 차단·암호화·소유권·정책 | ap-northeast-2 | 콘솔에서 만든 것을 가져옴 |
| `alerts.tf` | SNS 토픽·이메일 구독, EventBridge 규칙·대상 | ap-northeast-1(STS), us-east-1(IAM) | 새로 만듦 |

`imports.tf`의 `import` 블록이 콘솔 리소스를 상태로 가져온다. 가져온 리소스는 `plan`에서 변경·삭제가 0건이어야 한다.

알림 규칙은 2개다.

- OIDC 역할 전환 실패: `sts:AssumeRoleWithWebIdentity` 중 `errorCode`가 있는 이벤트. 백엔드가 STS를 부르는 리전(`sts_event_region`, 기본 ap-northeast-1)에 기록된다.
- 서비스 전용 자격증명 생성: `iam:CreateServiceSpecificCredential`. IAM은 us-east-1에만 기록된다.

EventBridge 규칙은 같은 리전의 SNS 토픽에만 보낼 수 있어서 리전마다 토픽과 이메일 구독을 하나씩 둔다. 확인 메일도 2통 온다. STS 호출은 읽기 전용 관리 이벤트라서 규칙 상태를 `ENABLED_WITH_ALL_CLOUDTRAIL_MANAGEMENT_EVENTS`로 둔다. 이 상태는 콘솔에서 고를 수 없다.

## 처음 한 번: 상태 버킷 만들기 (사람)

상태 파일 전용 S3 버킷을 만든다. 이름은 전역에서 겹치지 않아야 하므로 계정 ID를 붙이는 식으로 정한다. PowerShell 기준이다.

```powershell
$b = "<상태 버킷 이름>"
aws s3api create-bucket --bucket $b --region ap-northeast-2 --create-bucket-configuration LocationConstraint=ap-northeast-2
aws s3api put-bucket-versioning --bucket $b --versioning-configuration Status=Enabled
aws s3api put-public-access-block --bucket $b --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```

새 버킷은 기본으로 SSE-S3 암호화가 켜진다. 세 설정을 확인한다.

```powershell
aws s3api get-bucket-versioning --bucket $b      # Status: Enabled
aws s3api get-public-access-block --bucket $b    # 네 항목 모두 true
aws s3api get-bucket-encryption --bucket $b      # SSEAlgorithm: AES256
```

잠금은 S3 잠금 파일(`use_lockfile`)을 쓰므로 DynamoDB 테이블은 만들지 않는다.

## 적용 순서

1. 설정 파일 두 개를 복사하고 실제 값을 채운다.
   ```powershell
   cd infra
   Copy-Item backend.hcl.example backend.hcl
   Copy-Item terraform.tfvars.example terraform.tfvars
   ```
   모니터·구독 ID는 ARN의 마지막 UUID다.
2. 초기화한다.
   ```powershell
   terraform init -backend-config=backend.hcl
   ```
3. 계획을 만든다.
   ```powershell
   terraform plan -out=plan.tfplan
   ```
   처음에는 `Plan: 9 to import, 10 to add, 2 to change, 0 to destroy.`가 나와야 한다. 바뀌는 2건은 예산과 비용 이상 탐지 구독이다. 이메일·금액 변수가 `sensitive`라서 가져온 값에 가림 표시가 붙는 것뿐이며 실제 값은 같다(`limit_amount`에 "The value is unchanged"가 보인다). 2026-10-26 `sensitive`를 잠시 끄고 돌린 plan은 `0 to change`였다. 이 2건 말고 가져오는 리소스에 `~`(변경)나 `-`(삭제)가 보이면 적용하지 말고 해당 부분 출력을 이슈에 남긴다. 출력을 옮길 때는 계정 ID, 이메일, 로그 버킷 이름을 가린다. ARN에도 계정 ID가 들어 있다. 코드를 고친 뒤 다시 `plan`한다.

   plan 파일(`plan.tfplan`)에는 이메일·금액·계정 ID가 평문으로 들어간다. `.gitignore`가 막지만 적용 뒤에는 지운다.
4. 적용한다.
   ```powershell
   terraform apply plan.tfplan
   Remove-Item plan.tfplan
   ```
5. 받은편지함에서 `AWS Notification - Subscription Confirmation` 메일 2통의 확인 링크를 누른다.
6. 다시 `terraform plan`을 실행해 `No changes.`인지 확인한다.

## 시험 이벤트

적용과 구독 확인이 끝난 뒤 실행한다. 메일은 보통 몇 분 안에 오지만 늦을 수 있다. 15분이 지나도 안 오면 해당 리전의 CloudTrail 이벤트 기록에서 이벤트가 기록됐는지부터 본다.

**1. OIDC 역할 전환 실패 (ap-northeast-1)**

일부러 잘못된 토큰으로 호출한다. 오류가 나는 것이 정상이다.

```powershell
aws sts assume-role-with-web-identity --no-sign-request --region ap-northeast-1 --role-arn <Bedrock 역할 ARN> --role-session-name meg99-alert-test --web-identity-token invalid
```

형식이 틀린 토큰의 실패가 CloudTrail에 남는지는 아직 확인하지 않았다. 메일이 오지 않고 이벤트 기록에도 없으면 만료된 실제 OIDC 토큰으로 다시 시험한다.

**2. 서비스 전용 자격증명 생성 후 삭제 (us-east-1)**

권한 없는 임시 사용자에 1일짜리 키를 만들고 바로 지운다. `--query`로 ID만 받아서 키 값은 화면에 나오지 않는다. 그래도 Claude Code의 `!` 대신 별도 터미널에서 실행한다. PowerShell은 명령이 실패해도 다음 줄로 넘어가므로 한 줄씩 실행하고 `실패`가 보이면 멈춘다.

```powershell
$u = "meg99-alert-test"
aws iam create-user --user-name $u; if ($LASTEXITCODE) { "실패: 사용자 생성" }
$id = aws iam create-service-specific-credential --user-name $u --service-name bedrock.amazonaws.com --credential-age-days 1 --query ServiceSpecificCredential.ServiceSpecificCredentialId --output text; if ($LASTEXITCODE -or -not $id) { "실패: 키 생성 또는 ID 없음" }
aws iam delete-service-specific-credential --user-name $u --service-specific-credential-id $id; if ($LASTEXITCODE) { "실패: 키 삭제" }
aws iam delete-user --user-name $u; if ($LASTEXITCODE) { "실패: 사용자 삭제" }
aws iam get-user --user-name $u   # NoSuchEntity 오류가 나야 정리된 것이다
```

중간에 실패했으면 아래로 남은 키를 찾아 지운 뒤 사용자를 지운다.

```powershell
aws iam list-service-specific-credentials --user-name $u --query "ServiceSpecificCredentials[].ServiceSpecificCredentialId" --output text
```

메일 수신 시각을 이슈에 남긴다.

## 되돌리기

- **알림만 끄기:** `alerts.tf`를 지우고 `plan`→`apply`한다. 토픽·구독·규칙 10개가 삭제된다.
- **가져오기 PR(MEG-99)은 revert하지 않는다.** revert하면 가져온 예산·트레일·버킷 설정이 삭제 대상이 된다. 가져온 리소스는 아래 `removed` 블록으로만 관리에서 뺀다.
- **이후 변경 되돌리기:** 가져오기 이후의 변경 PR은 revert한 뒤 `plan`으로 차이를 확인하고 `apply`한다. `plan`에 가져온 리소스의 삭제가 보이면 적용하지 않는다.
- **가져온 리소스를 Terraform 관리에서 빼기:** 리소스 블록을 지우고 아래 블록을 넣어 `apply`한다. AWS에서는 지워지지 않는다.
  ```hcl
  removed {
    from = aws_cloudtrail.audit
    lifecycle {
      destroy = false
    }
  }
  ```
- `terraform destroy`는 쓰지 않는다. 로그 버킷은 `prevent_destroy`로 막아 두었다.

## 알아 둘 것

- 비용 이상 탐지 모니터 이름이 콘솔에서 `Daily summaries`로 저장됐다. 가져오기에서 변경 0건을 맞추려고 그대로 두었다. 이름을 바꾸려면 가져오기가 끝난 뒤 별도 변경으로 고친다.
- `sts_event_region`은 백엔드 `BEDROCK_REGION`과 같아야 한다. 백엔드 리전을 바꾸면 이 값도 바꾼다.
- 로컬 검사: `terraform fmt -check -recursive`, `terraform init -backend=false`, `terraform validate`. CI에서는 Terraform을 실행하지 않는다.
- provider를 올릴 때는 `terraform providers lock -platform=windows_amd64 -platform=linux_amd64 -platform=darwin_arm64 -platform=darwin_amd64`로 잠금 파일을 갱신해 커밋한다.
