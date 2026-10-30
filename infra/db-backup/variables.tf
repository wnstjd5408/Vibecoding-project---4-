# 공개 저장소라서 계정마다 다른 값은 terraform.tfvars(커밋 안 함)로만 넘긴다.

variable "owner" {
  description = "공용 실습 계정의 리소스 주인. 이메일 @ 앞부분. infra/의 owner와 같은 값을 쓴다."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]*$", var.owner))
    error_message = "owner는 소문자·숫자·하이픈만 쓴다."
  }
}

variable "home_region" {
  description = "백업 버킷을 만드는 리전. .github/workflows/db-backup.yml의 BACKUP_REGION과 같아야 한다."
  type        = string
  default     = "ap-northeast-2"
}

# 2026-10-30 Q6 결정: 최근 8개 보관(주 1회 기준 약 2개월). 수동 실행도 1개로 센다.
# 밀려난 이전 버전도 14일은 남기므로(main.tf) 평소에는 9~10개가 있다.
variable "retention_count" {
  description = "db/latest/backup.tar와 glossary-images/latest/images.tar마다 남기는 최소 백업 수(현재 버전 포함)"
  type        = number
  default     = 8

  validation {
    condition     = var.retention_count >= 2 && var.retention_count <= 101
    error_message = "retention_count는 2~101이다(S3 NewerNoncurrentVersions 상한 100 + 현재 버전 1)."
  }
}

# 계정 ID와 사용자 이름이 들어 있어 기본값을 두지 않고 terraform.tfvars로만 넘긴다.
# IAM 사용자면 arn:aws:iam::<계정 ID>:user/<이름>을 넣는다. 역할(SSO 등)로 로그인하면 세션 ARN이 아니라
# 경로까지 들어간 역할 ARN을 넣는다(aws:PrincipalArn은 경로를 포함한 역할 ARN으로 평가된다).
# get-caller-identity의 assumed-role ARN에는 경로가 없으므로 `aws iam get-role --role-name <역할> --query Role.Arn`으로 확인한다.
# SSO 역할은 예: arn:aws:iam::<계정 ID>:role/aws-reserved/sso.amazonaws.com/<리전>/AWSReservedSSO_<이름>_<ID>
variable "backup_admin_arns" {
  description = "백업을 읽고 지우고 보관 설정을 바꿀 수 있는 IAM 사용자·역할 ARN. 이 밖의 주체는 버킷 정책이 거부한다."
  type        = list(string)

  validation {
    condition = length(var.backup_admin_arns) > 0 && alltrue([
      for arn in var.backup_admin_arns : can(regex("^arn:aws:iam::[0-9]{12}:(user|role)/", arn))
    ])
    error_message = "backup_admin_arns에는 IAM 사용자 또는 역할 ARN을 하나 이상 넣는다(assumed-role 세션 ARN은 안 된다)."
  }
}

# infra/github-oidc의 같은 이름 변수와 같은 값이다. 숫자 ID는 공개 저장소의 공개 식별자라 커밋해도 된다.
variable "github_subject_repository" {
  description = "백업 워크플로를 실행할 GitHub 저장소의 sub 클레임 표기(owner@ID/name@ID)"
  type        = string
  default     = "wnstjd5408@73061276/Vibecoding-project---4-@1421732974"
}

variable "backup_environment" {
  description = "백업 job이 쓰는 GitHub Environment 이름. .github/workflows/db-backup.yml의 environment와 같아야 한다."
  type        = string
  default     = "db-backup"
}
