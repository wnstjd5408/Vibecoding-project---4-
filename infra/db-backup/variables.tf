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
# 수명 주기 규칙은 하루 단위로 돌아서 새 백업 직후에는 하루 동안 9개가 있을 수 있다.
variable "retention_count" {
  description = "db/latest/와 glossary-images/latest/의 키마다 남기는 백업 수(현재 버전 포함)"
  type        = number
  default     = 8

  validation {
    condition     = var.retention_count >= 2 && var.retention_count <= 101
    error_message = "retention_count는 2~101이다(S3 NewerNoncurrentVersions 상한 100 + 현재 버전 1)."
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
