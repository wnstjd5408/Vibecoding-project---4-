# 공개 저장소라서 계정마다 다른 값과 비공개 값은 terraform.tfvars(커밋 안 함)로만 넘긴다.

variable "owner" {
  description = "공용 실습 계정의 리소스 주인. 이메일 @ 앞부분을 적는다. Owner 태그와 이름 접두사에 쓴다."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]*$", var.owner))
    error_message = "owner는 소문자·숫자·하이픈만 쓴다."
  }
}

variable "home_region" {
  description = "CloudTrail 트레일과 로그 버킷이 있는 리전"
  type        = string
  default     = "ap-northeast-2"
}

variable "sts_event_region" {
  description = "백엔드가 STS를 부르는 리전. backend/app/bedrock.py의 BEDROCK_REGION 기본값과 같게 둔다."
  type        = string
  default     = "ap-northeast-1"
}

variable "alert_email" {
  description = "예산·비용 이상·감사 이벤트 알림을 받을 이메일"
  type        = string
  sensitive   = true
}

variable "monthly_budget_usd" {
  description = "월 예산 한도(USD), 문자열"
  type        = string
  sensitive   = true
}

variable "budget_start" {
  description = "월 예산 시작일(YYYY-MM-DD_hh:mm)"
  type        = string
  default     = "2026-10-01_00:00"
}

variable "cloudtrail_bucket_name" {
  description = "CloudTrail이 만든 로그 버킷 이름"
  type        = string
}

variable "anomaly_monitor_id" {
  description = "비용 이상 탐지 모니터 ARN의 마지막 부분(UUID)"
  type        = string
}

variable "anomaly_subscription_id" {
  description = "비용 이상 탐지 구독 ARN의 마지막 부분(UUID)"
  type        = string
}
