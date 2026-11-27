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
  description = "IAM 리소스를 만드는 provider 리전(IAM은 글로벌이라 값은 중요하지 않다)"
  type        = string
  default     = "ap-northeast-2"
}

variable "state_bucket_name" {
  description = "Terraform 상태를 둔 S3 버킷 이름. plan 파일도 이 버킷의 plans/ 아래에 둔다."
  type        = string
}

variable "cloudtrail_bucket_name" {
  description = "CloudTrail 로그 버킷 이름. plan 역할이 이 버킷의 설정을 읽는다."
  type        = string
}

# 이 저장소는 OIDC 토큰의 sub가 불변 형식이다(use_immutable_subject). 소유자·저장소 이름 뒤에 숫자 ID가
# 붙는다. 이름만 쓴 옛 형식(owner/name)으로는 역할 전환이 거부된다(2026-10-28 MEG-100 첫 CD 실행).
# 값은 `gh api repos/<owner>/<name>/actions/oidc/customization/sub`의 sub_claim_prefix에서
# 앞의 "repo:"를 뺀 것이다. 두 ID는 공개 저장소의 공개 식별자라 커밋해도 된다.
variable "github_subject_repository" {
  description = "CD를 실행할 GitHub 저장소의 sub 클레임 표기(owner@ID/name@ID). 역할 신뢰 정책의 sub를 이 저장소로 제한한다."
  type        = string
  default     = "wnstjd5408@73061276/cs-training@1421732974"
}

# 저장소 이름을 바꾸는 동안 옛 이름과 새 이름의 sub를 함께 허용할 때 쓴다(MEG-301에서 사용).
# 소유자·저장소 숫자 ID는 이름을 바꿔도 그대로다. 평소에는 비워 둔다.
variable "github_subject_repository_aliases" {
  description = "github_subject_repository와 함께 신뢰할 추가 sub 표기(owner@ID/name@ID). 저장소 이름 변경 기간에만 쓴다."
  type        = list(string)
  default     = []
  validation {
    condition     = alltrue([for r in var.github_subject_repository_aliases : can(regex("^[A-Za-z0-9_.-]+@[0-9]+/[A-Za-z0-9_.-]+@[0-9]+$", r))])
    error_message = "owner@ID/name@ID 형식만 허용한다(와일드카드 금지)."
  }
  # 이름만 다른 같은 저장소여야 한다. 소유자·저장소 숫자 ID가 github_subject_repository와 다르면 거부한다.
  validation {
    condition     = alltrue([for r in var.github_subject_repository_aliases : replace(r, "/^[^@]+@([0-9]+)/[^@]+@([0-9]+)$/", "$1/$2") == replace(var.github_subject_repository, "/^[^@]+@([0-9]+)/[^@]+@([0-9]+)$/", "$1/$2")])
    error_message = "별칭의 소유자·저장소 ID는 github_subject_repository와 같아야 한다."
  }
}

variable "plan_environment" {
  description = "plan job이 쓰는 GitHub Environment 이름. 워크플로의 environment와 같아야 한다."
  type        = string
  default     = "infra-plan"
}

variable "apply_environment" {
  description = "apply job이 쓰는 GitHub Environment 이름. 필수 승인자를 둔다."
  type        = string
  default     = "infra-apply"
}
