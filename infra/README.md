# infra — AWS 운영 설정

AWS 계정의 비용 경보, 감사 로그, 감사 이벤트 알림을 Terraform으로 관리한다(MEG-99). AI는 코드와 PR을 만들고 `init`·`plan`까지 실행할 수 있다. `apply`와 상태 버킷 생성, 시험 이벤트는 사람이 한다(2026-10-26 결정). `main`에 병합한 뒤의 변경은 GitHub Actions가 plan을 만들고 사람이 승인하면 적용한다("CD로 적용" 절, MEG-100).

공개 저장소라서 계정 ID·이메일·예산 금액·버킷 이름은 커밋하지 않는다. 이 값은 `terraform.tfvars`와 `backend.hcl`에만 둔다. 두 파일은 `.gitignore`에 들어 있다. 상태 파일과 plan 파일에도 이 값이 평문으로 들어가므로 상태 버킷을 읽을 수 있는 사람은 비공개 값도 볼 수 있다.

## 공용 실습 계정 규칙

이 계정은 메가존클라우드가 여러 명에게 함께 준 실습 계정이고, 비용이 실제로 청구된다. `infra/`로 만들거나 바꾸는 리소스는 아래 규칙을 지킨다.

- **Owner 태그:** 모든 리소스에 `Owner = 이메일 @ 앞부분` 태그를 단다. provider의 `default_tags`가 `var.owner` 값으로 자동으로 붙인다. Terraform 밖에서 만든 상태 버킷은 사람이 직접 태그를 단다("처음 한 번" 절).
- **이름 접두사:** 새로 만드는 리소스 이름 앞에 `<owner>-`를 붙여 다른 사람 리소스와 구분한다. 콘솔에서 만들어 가져온 예산·이상 탐지 구독·트레일·로그 버킷은 이름을 바꾸면 새로 만들어지므로 이름을 그대로 두고 Owner 태그로 구분한다.
- **정리:** 수업이 끝나면 직접 만든 리소스를 지운다. 절차와 확인 방법은 "정리(삭제) 방법" 절에 있다.
- **시간 과금 리소스:** 이 폴더의 리소스(예산, 비용 이상 탐지, CloudTrail 관리 이벤트 트레일, S3, SNS, EventBridge, IAM OIDC 공급자·역할)는 시간당 과금이 없다. EC2·NAT 게이트웨이·탄력적 IP·RDS·OpenSearch·SageMaker 엔드포인트처럼 켜 두는 동안 과금되는 리소스를 추가할 때는 쓴 직후 지우는 절차를 함께 적는다. EC2는 중지가 아니라 종료한다. 중지만 하면 EBS 볼륨과 탄력적 IP는 계속 과금된다.
- **사용 금지:** AWS Marketplace 유료 구독, Support 플랜 변경, Shield Advanced 같은 고비용 구독 서비스는 만들지 않는다. 계획에 들어 있으면 만들기 전에 알린다.
- **정기 점검:** 운영 담당자가 계정을 정기 점검한다. `Owner` 태그가 없거나 오래 쓰지 않은 리소스는 안내 없이 삭제될 수 있다. 보관할 데이터(예: CloudTrail 로그)는 따로 백업한다.

## 관리하는 것

| 파일 | 리소스 | 리전 | 출처 |
|---|---|---|---|
| `budget.tf` | 월 예산 `cs-learning-monthly`와 경보 4개(실제 50·80·100%, 예상 100%), 비용 이상 탐지 모니터 `<owner>-cs-learning-cost-monitor`·구독 `daily-cost-anomaly` | 글로벌 | 콘솔에서 만든 것을 가져옴 |
| `cloudtrail.tf` | 트레일 `cs-learning-audit`, 로그 버킷과 공개 차단·암호화·소유권·정책 | ap-northeast-2 | 콘솔에서 만든 것을 가져옴 |
| `alerts.tf` | SNS 토픽 `<owner>-cs-learning-audit-alerts`·이메일 구독, EventBridge 규칙 `<owner>-cs-learning-…`·대상 | ap-northeast-1(STS), us-east-1(IAM) | 새로 만듦 |
| `github-oidc/` | GitHub OIDC 공급자, IAM 역할 `<owner>-infra-plan`·`<owner>-infra-apply` | 글로벌 | 새로 만듦. CD 전용이며 상태 파일이 따로다. CD가 아니라 사람이 로컬에서 적용한다 |

`imports.tf`의 `import` 블록이 콘솔 리소스를 상태로 가져온다. 가져온 리소스는 `plan`에서 변경·삭제가 0건이어야 한다.

알림 규칙은 2개다.

- OIDC 역할 전환 실패: `sts:AssumeRoleWithWebIdentity` 중 `errorCode`가 있는 이벤트. 백엔드가 STS를 부르는 리전(`sts_event_region`, 기본 ap-northeast-1)에 기록된다.
- 서비스 전용 자격증명 생성: `iam:CreateServiceSpecificCredential`. IAM은 us-east-1에만 기록된다.

EventBridge 규칙은 같은 리전의 SNS 토픽에만 보낼 수 있어서 리전마다 토픽과 이메일 구독을 하나씩 둔다. 확인 메일도 2통 온다. STS 호출은 읽기 전용 관리 이벤트라서 규칙 상태를 `ENABLED_WITH_ALL_CLOUDTRAIL_MANAGEMENT_EVENTS`로 둔다. 이 상태는 콘솔에서 고를 수 없다.

## 처음 한 번: 상태 버킷 만들기 (사람)

상태 파일 전용 S3 버킷을 만든다. 이름은 전역에서 겹치지 않아야 하므로 owner 접두사와 계정 ID를 붙인다(예: `<owner>-cs-learning-tfstate-<계정 ID>`). 이 버킷은 Terraform 밖에서 만들므로 Owner 태그도 직접 단다. PowerShell 기준이다.

```powershell
$b = "<상태 버킷 이름>"
$o = "<owner>"
aws s3api create-bucket --bucket $b --region ap-northeast-2 --create-bucket-configuration LocationConstraint=ap-northeast-2
aws s3api put-bucket-versioning --bucket $b --versioning-configuration Status=Enabled
aws s3api put-public-access-block --bucket $b --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-tagging --bucket $b --tagging "TagSet=[{Key=Owner,Value=$o}]"
```

새 버킷은 기본으로 SSE-S3 암호화가 켜진다. 네 설정을 확인한다.

```powershell
aws s3api get-bucket-versioning --bucket $b      # Status: Enabled
aws s3api get-public-access-block --bucket $b    # 네 항목 모두 true
aws s3api get-bucket-encryption --bucket $b      # SSEAlgorithm: AES256
aws s3api get-bucket-tagging --bucket $b         # Owner 태그
```

잠금은 S3 잠금 파일(`use_lockfile`)을 쓰므로 DynamoDB 테이블은 만들지 않는다.

## 적용 순서

1. 설정 파일 두 개를 복사하고 실제 값을 채운다.
   ```powershell
   cd infra
   Copy-Item backend.hcl.example backend.hcl
   Copy-Item terraform.tfvars.example terraform.tfvars
   ```
   `owner`에는 이메일 @ 앞부분을 적는다. 모니터·구독 ID는 ARN의 마지막 UUID다.
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

형식이 틀린 토큰으로는 시험할 수 없다. 2026-10-26 `--web-identity-token invalid`로 호출하면 `InvalidIdentityToken`("not a valid JWT")이 났지만, 이틀 뒤까지 CloudTrail 기록이 없었고 규칙도 반응하지 않았다. 토큰 형식부터 틀린 요청은 CloudTrail에 남지 않는 것으로 보인다.

이 규칙은 OIDC 공급자와 역할이 있는 상태에서 실제 토큰이 거부될 때(예: 2026-10-22에 기록된 `AccessDenied`) 반응한다. 지금 계정에는 OIDC 역할이 없어서 이 시험은 역할을 다시 만들 때 한다. 그 전에는 규칙 상태(`ENABLED_WITH_ALL_CLOUDTRAIL_MANAGEMENT_EVENTS`)와 구독 확인, 아래 2번 시험으로 SNS 전달 경로를 확인한다(2026-10-28 결정).

**2. 서비스 전용 자격증명 생성 후 삭제 (us-east-1)**

권한 없는 임시 사용자(owner 접두사와 Owner 태그를 붙인다)에 1일짜리 키를 만들고 바로 지운다. `--query`로 ID만 받아서 키 값은 화면에 나오지 않는다. 그래도 Claude Code의 `!` 대신 별도 PowerShell 창에서 실행한다.

PowerShell은 명령이 실패해도 다음 줄로 넘어가므로 아래 블록은 실패하면 바로 멈춘다. `--tags` 값은 따옴표로 감싼다. 감싸지 않으면 PowerShell이 쉼표를 배열 구분자로 읽어 `ValidationError`가 난다.

```powershell
$o = "<owner>"; $u = "$o-meg99-alert-test"
& {
  aws iam create-user --user-name $u --tags "Key=Owner,Value=$o" | Out-Null
  if ($LASTEXITCODE) { "실패: 사용자 생성"; return }
  $id = aws iam create-service-specific-credential --user-name $u --service-name bedrock.amazonaws.com --credential-age-days 1 --query ServiceSpecificCredential.ServiceSpecificCredentialId --output text
  if ($LASTEXITCODE -or -not $id) { "실패: 키 생성 — 사용자만 지움"; aws iam delete-user --user-name $u; return }
  aws iam delete-service-specific-credential --user-name $u --service-specific-credential-id $id
  if ($LASTEXITCODE) { "실패: 키 삭제 — 아래 명령으로 정리"; return }
  aws iam delete-user --user-name $u
  if ($LASTEXITCODE) { "실패: 사용자 삭제 — 아래 명령으로 정리"; return }
  "정리 완료"
}
aws iam get-user --user-name $u   # NoSuchEntity 오류가 나야 정리된 것이다
```

이 규칙은 키 생성이 실패한 시도(예: 없는 사용자)에도 알림을 보낸다.

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
- 수업 중에는 `terraform destroy`를 쓰지 않는다. 로그 버킷은 `prevent_destroy`로 막아 두었다. 수업이 끝난 뒤의 삭제는 아래 "정리(삭제) 방법"을 따른다.

## CD로 적용 (MEG-100)

`infra/` 변경을 `main`에 병합하면 `.github/workflows/infra-cd.yml`이 plan을 만들고, 사람이 승인한 뒤에 같은 plan을 적용한다. 로컬 AWS 자격증명이 없어도 `infra/`를 바꿀 수 있다. 첫 적용과 `infra/github-oidc/` 변경은 CD 대상이 아니고 사람이 로컬에서 한다.

**흐름**

1. `infra/*.tf`나 `infra/.terraform.lock.hcl`을 바꾼 PR이 `main`에 병합된다. README·예시 파일만 바꾼 병합과 `infra/github-oidc/`는 실행하지 않는다. 수동 실행(`workflow_dispatch`)도 된다. PR 단계에서는 plan이 돌지 않는다. PR 검토 때는 로컬 `plan`을 쓴다.
2. **Plan** job(Environment `infra-plan`)이 OIDC로 읽기 전용 역할 `<owner>-infra-plan`을 맡아 `plan`을 만든다. 로그에는 `Plan: …` 줄과 바뀌는 리소스 주소·동작 목록만 남는다. 바뀔 것이 없으면 여기서 끝난다.
3. plan 파일을 상태 버킷의 `plans/<실행 번호>.tfplan`에 올린다. 공개 저장소의 Actions 아티팩트는 쓰지 않는다.
4. **Apply** job(Environment `infra-apply`)은 필수 승인자가 승인하기 전에는 시작하지 않는다. 승인하면 역할 `<owner>-infra-apply`를 맡아 올린 plan 파일만 적용하고 파일을 지운다. 그 사이 상태가 바뀌었으면 Terraform이 적용을 거부한다.
5. 같은 시각에 실행은 하나만 돈다(`concurrency`).

**처음 한 번 (사람)**

1. **plan 파일 만료 규칙:** 상태 버킷은 버전 관리가 켜져 있어 지워도 이전 버전이 남는다. `plans/` 아래만 하루 뒤 지우는 규칙을 건다. 승인을 거절해 남은 plan 파일도 이 규칙으로 사라진다. 이 명령은 버킷의 기존 수명 주기 규칙을 덮어쓴다(새 버킷에는 규칙이 없다).
   ```powershell
   $b = "<상태 버킷 이름>"
   '{"Rules":[{"ID":"expire-plans","Status":"Enabled","Filter":{"Prefix":"plans/"},"Expiration":{"Days":1},"NoncurrentVersionExpiration":{"NoncurrentDays":1}}]}' | Set-Content -Encoding ascii lifecycle.json
   aws s3api put-bucket-lifecycle-configuration --bucket $b --lifecycle-configuration file://lifecycle.json
   Remove-Item lifecycle.json
   aws s3api get-bucket-lifecycle-configuration --bucket $b   # expire-plans 규칙이 보여야 한다
   ```
2. **역할 만들기:** `infra/github-oidc/`에서 사람이 로컬에서 적용한다. `owner`·버킷 이름은 `infra/`와 같은 값을 쓴다. OIDC 공급자는 계정에 하나만 만들 수 있다. 이미 있으면 `apply`가 `EntityAlreadyExists`로 실패하므로 먼저 `aws iam list-open-id-connect-providers`로 확인한다(2026-10-28 이 계정에는 없었다).
   ```powershell
   cd infra\github-oidc
   Copy-Item terraform.tfvars.example terraform.tfvars   # 값을 채운다
   terraform init "-backend-config=../backend.hcl"
   terraform plan "-out=plan.tfplan"
   terraform apply plan.tfplan
   Remove-Item plan.tfplan
   terraform output
   ```
   `plan`은 `Plan: 5 to add, 0 to change, 0 to destroy.`가 나와야 한다(공급자 1, 역할 2, 역할 정책 2). 출력된 역할 ARN 두 개를 다음 단계에서 쓴다. ARN에는 계정 ID가 있으므로 이슈나 PR에 옮기지 않는다.
3. **GitHub Environment 만들기:** 저장소 Settings → Environments에서 두 개를 만든다.
   - `infra-plan`: Deployment branches and tags를 **Selected branches and tags**로 하고 `main`만 넣는다.
   - `infra-apply`: 같은 배포 브랜치 규칙에 **Required reviewers**로 승인자를 넣는다. 승인자가 병합한 사람과 같아서 "Prevent self-review"는 끈다. 승인은 여전히 별도 클릭이다.
   - 이 브랜치 규칙이 `main` 밖의 브랜치가 두 역할을 맡지 못하게 하는 장치다. 역할 신뢰 정책은 저장소와 Environment 이름만 보고 브랜치는 보지 않는다.
   - 신뢰 정책의 `sub`는 이 저장소의 불변 형식(`repo:<owner>@<소유자 ID>/<name>@<저장소 ID>:environment:<이름>`)이다. 이름만 쓴 `repo:<owner>/<name>:environment:…`로는 역할 전환이 거부된다(`Not authorized to perform sts:AssumeRoleWithWebIdentity`). 값은 `gh api repos/<owner>/<name>/actions/oidc/customization/sub`의 `sub_claim_prefix`에서 확인하고, `variables.tf`의 `github_subject_repository`에 있다. 저장소를 다른 소유자로 넘기거나 새로 만들면 ID가 바뀌므로 이 값을 고쳐 다시 적용한다.
4. **비밀값 넣기:** 저장소 비밀값이 아니라 각 Environment의 Secrets에 넣는다. 저장소 비밀값은 `main` 밖의 브랜치 워크플로도 읽을 수 있다.

   | Environment | 이름 | 값 |
   |---|---|---|
   | `infra-plan` | `AWS_ROLE_ARN` | `terraform output`의 `plan_role_arn` |
   | `infra-plan` | `TF_STATE_BUCKET` | 상태 버킷 이름 |
   | `infra-plan` | `TF_VARS_JSON` | 아래 한 줄 JSON |
   | `infra-apply` | `AWS_ROLE_ARN` | `terraform output`의 `apply_role_arn` |
   | `infra-apply` | `TF_STATE_BUCKET` | 상태 버킷 이름 |

   `TF_VARS_JSON`은 `infra/terraform.tfvars`의 변수를 한 줄 JSON으로 합친 값이다. 값마다 비밀값으로 두면 예산 같은 짧은 숫자가 로그의 다른 숫자까지 `***`로 가린다. 아래 명령이 클립보드에 복사하므로 그대로 붙여 넣는다.
   ```powershell
   @{
     owner                   = "<owner>"
     alert_email             = "<알림 이메일>"
     monthly_budget_usd      = "<월 예산>"
     cloudtrail_bucket_name  = "<로그 버킷 이름>"
     anomaly_monitor_id      = "<모니터 UUID>"
     anomaly_subscription_id = "<구독 UUID>"
   } | ConvertTo-Json -Compress | Set-Clipboard
   ```
   `infra/`에 변수를 추가하면 이 JSON에도 키를 추가해야 plan이 돈다. `budget_start`·`home_region`·`sts_event_region`은 기본값을 쓰면 넣지 않는다.

**승인하는 법**

1. 저장소 Actions 탭에서 `Infra CD` 실행을 연다. Plan job 로그의 `Plan: …` 줄과 "승인할 변경" 목록을 병합한 PR과 비교한다. 목록에는 `create`, `update`, `delete`, `import+no-op` 같은 동작과 리소스 주소만 있다. 값은 없다. 값 변경은 PR diff로 확인한다.
2. `delete`가 있거나 PR에 없는 리소스가 보이면 승인하지 않고 거절한다.
3. 이상이 없으면 **Review deployments**에서 `infra-apply`를 승인한다.
4. Apply job 로그의 `Apply complete!` 줄을 확인한다. 이어서 로컬 또는 다음 CD 실행의 `plan`이 `No changes.`인지 본다.

**실패했을 때**

- **plan·init·apply가 실패:** 공개 로그라서 Terraform 출력을 남기지 않는다. 종료 코드만 보인다. 같은 커밋을 로컬에서 `plan`해 원인을 본다.
- **apply가 `AccessDenied`:** `infra/`에 새 리소스 종류를 추가했는데 apply 역할이 모르는 것이다. `infra/github-oidc/main.tf`의 정책에 권한을 더하는 PR을 올리고, 병합 뒤 사람이 로컬에서 `infra/github-oidc`를 적용한다. 의도적으로 뺀 권한(트레일·로그 버킷·로그 버킷 정책 삭제, IAM 쓰기)이 필요한 plan은 로컬에서 직접 적용한다.
- **apply가 중간에 실패:** 일부 리소스는 이미 바뀌었을 수 있다. 상태를 믿고 로컬에서 `plan`해 차이를 본 뒤 다시 `main`에 고치는 PR을 올리거나 로컬에서 적용한다. 상태 파일은 apply가 실패해도 쓴 곳까지 기록된다.
- **승인을 거절했거나 시간이 지났다:** plan 파일은 하루 안에 만료 규칙으로 사라진다. 다시 적용하려면 Actions에서 `Infra CD`를 `main`에서 수동 실행하거나 실행을 다시 돌린다. 오래된 plan은 상태가 바뀌었으면 적용되지 않는다.

**되돌리기**

- 변경을 되돌리려면 변경 PR을 revert하는 PR을 올려 병합하고 CD 승인을 거친다. 가져온 리소스를 삭제하는 revert는 위 "되돌리기" 절의 주의를 따른다.
- CD를 끄려면 `.github/workflows/infra-cd.yml`을 지우는 PR을 올린다. AWS 쪽 역할은 "정리(삭제) 방법"의 5단계에서 지운다. 비상 때는 `infra-apply` Environment를 지우거나 역할 정책을 비워도 apply가 멈춘다.

**알아 둘 것**

- 로그에는 리소스 주소가 나온다. `for_each` 키나 이름에 이메일·계정 ID 같은 비공개 값을 넣지 않는다.
- plan 파일에는 변수 값이 평문으로 들어 있다. 파일은 비공개·암호화된 상태 버킷에만 있고 하루 안에 지워진다. 그동안은 상태 버킷을 읽을 수 있는 사람이 볼 수 있다. plan 역할은 `plans/`에 쓰기만 하고 읽지 못한다. apply 역할만 읽는다.
- Environment 비밀값은 저장소 관리자가 덮어쓸 수 있다. 비밀값을 바꾼 이력은 GitHub 감사 기록에 남는다.
- OIDC 역할 전환이 거부되면 `infra/alerts.tf`의 STS 알림 규칙이 반응한다. 워크플로는 이 규칙이 보는 리전(`ap-northeast-1`)으로 역할을 요청한다.
- IAM 역할의 `description`에는 한글을 쓰지 못한다(ASCII·Latin-1만). 한글이 있으면 `plan`·`validate`는 통과하고 `apply`의 `CreateRole`에서 `ValidationError`가 난다(2026-10-28 MEG-100 첫 `apply`에서 겪음). 중간에 실패한 `apply`는 이미 만든 리소스(OIDC 공급자)를 상태에 남기므로 코드를 고친 뒤 `plan`을 다시 만들어 적용한다.

## 정리(삭제) 방법

수업이 끝나면 이 폴더가 만든 리소스와 상태 버킷을 모두 지운다. 사람이 PowerShell에서 실행한다. `$o`는 owner, `$log`는 로그 버킷 이름, `$state`는 상태 버킷 이름이다.

1. **백업:** 보관할 CloudTrail 로그가 있으면 내려받는다.
   ```powershell
   aws s3 sync "s3://$log" .\cloudtrail-backup
   ```
2. **트레일부터 지운다.** 트레일이 남아 있으면 로그가 계속 쌓여 버킷을 비울 수 없다.
   ```powershell
   terraform destroy -target="aws_cloudtrail.audit"
   ```
3. **로그 버킷을 비운다.** 로그 버킷은 버전 관리가 꺼져 있어 객체만 지우면 된다.
   ```powershell
   aws s3 rm "s3://$log" --recursive
   ```
4. **나머지를 지운다.** `cloudtrail.tf`에서 `prevent_destroy = true` 줄을 로컬에서만 지운 뒤 실행한다. 이 수정은 커밋하지 않는다.
   ```powershell
   terraform destroy
   ```
   마지막 줄이 `Destroy complete!`이고 오류가 없어야 한다.
5. **CD 역할을 지운다.** GitHub Environment 비밀값과 워크플로는 저장소에서 따로 지운다. 이 폴더는 상태 버킷을 쓰므로 상태 버킷을 지우기 전에 실행한다.
   ```powershell
   cd github-oidc
   terraform destroy
   ```
   마지막 줄이 `Destroy complete! Resources: 5 destroyed.`여야 한다.
6. **상태 버킷을 지운다.** 버전 관리가 켜져 있어 이전 버전까지 지워야 한다. S3 콘솔에서 상태 버킷을 고르고 **비우기(Empty)** 다음 **삭제(Delete)** 를 누른다.
7. **삭제 확인:** 아래 명령이 모두 빈 결과나 NotFound(404) 오류를 내야 한다.
   ```powershell
   aws budgets describe-budgets --account-id (aws sts get-caller-identity --query Account --output text) --query "Budgets[?BudgetName=='cs-learning-monthly']"
   aws ce get-anomaly-monitors --query "AnomalyMonitors[?contains(MonitorName, '$o')]"
   aws cloudtrail describe-trails --region ap-northeast-2 --query "trailList[?Name=='cs-learning-audit']"
   aws sns list-topics --region ap-northeast-1 --query "Topics[?contains(TopicArn, '$o-')]"
   aws sns list-topics --region us-east-1 --query "Topics[?contains(TopicArn, '$o-')]"
   aws events list-rules --region ap-northeast-1 --name-prefix "$o-"
   aws events list-rules --region us-east-1 --name-prefix "$o-"
   aws s3api head-bucket --bucket $log     # 404
   aws s3api head-bucket --bucket $state   # 404
   aws iam list-open-id-connect-providers  # token.actions.githubusercontent.com이 없어야 한다
   aws iam get-role --role-name "$o-infra-plan"    # NoSuchEntity
   aws iam get-role --role-name "$o-infra-apply"   # NoSuchEntity
   ```

## 알아 둘 것

- 비용 이상 탐지 모니터 이름은 콘솔에서 `Daily summaries`로 잘못 저장돼 있었다. 가져오기가 끝난 뒤 `<owner>-cs-learning-cost-monitor`로 고쳤다(제자리 변경).
- `alerts.tf` 리소스 이름을 바꾸면 토픽과 구독이 새로 만들어지므로 확인 메일 2통을 다시 눌러야 한다.
- `sts_event_region`은 백엔드 `BEDROCK_REGION`과 같아야 한다. 백엔드 리전을 바꾸면 이 값도 바꾼다.
- 로컬 검사: `terraform fmt -check -recursive`, `terraform init -backend=false`, `terraform validate`. `infra/`와 `infra/github-oidc/`에서 각각 실행한다. PR CI에서는 Terraform을 실행하지 않는다. `main` 병합 뒤의 CD만 실행한다.
- provider를 올릴 때는 `terraform providers lock -platform=windows_amd64 -platform=linux_amd64 -platform=darwin_arm64 -platform=darwin_amd64`로 잠금 파일을 갱신해 커밋한다.
