variable "owner" {
  type = string
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,29}$", var.owner))
    error_message = "owner는 30자 이하 소문자·숫자·하이픈이다."
  }
}

variable "home_region" {
  type    = string
  default = "ap-northeast-2"
}

variable "operations_repository" {
  description = "사람이 생성하고 private임을 확인한 백업 전용 owner/repo. 공개 앱 저장소는 사용할 수 없다."
  type        = string
  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.operations_repository)) && lower(var.operations_repository) != "wnstjd5408/vibecoding-project---4-"
    error_message = "공개 앱 저장소와 다른 owner/repo를 입력한다."
  }
}

variable "operations_oidc_subject" {
  description = "운영 저장소 main의 실제 OIDC sub. repo:OWNER/REPO:ref:refs/heads/main (ID 포함 형식이면 실제 값을 사용)."
  type        = string
  validation {
    condition     = can(regex("^repo:[A-Za-z0-9_.@-]+/[A-Za-z0-9_.@-]+:ref:refs/heads/main$", var.operations_oidc_subject)) && replace(var.operations_oidc_subject, "/@[0-9]+/", "") == "repo:${var.operations_repository}:ref:refs/heads/main"
    error_message = "와일드카드 없는 운영 저장소 main 브랜치 sub를 입력한다."
  }
}

variable "runner_version" {
  type    = string
  default = "2.338.2"
  validation {
    condition     = can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+$", var.runner_version))
    error_message = "러너 버전은 숫자 세 자리 형식이다."
  }
}

variable "runner_sha256" {
  description = "actions/runner 공식 linux-x64 릴리스 아카이브 SHA256. 버전과 함께 갱신한다."
  type        = string
  default     = "baebf204307bac6193480852732f0aba2ae97b6c5597c244f4d5558390147c40"
  validation {
    condition     = can(regex("^[a-f0-9]{64}$", var.runner_sha256))
    error_message = "64자리 SHA256이 필요하다."
  }
}
