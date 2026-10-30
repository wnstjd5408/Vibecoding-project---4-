# 공개 저장소라서 계정·팀마다 다른 값은 terraform.tfvars(커밋 안 함)로만 넘긴다.

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

# 팀 슬러그에 개인 식별 정보가 들어 있을 수 있어 기본값을 두지 않는다.
variable "vercel_team_slug" {
  description = "Vercel 팀 URL의 슬러그. OIDC issuer·aud·sub에 들어간다."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]*$", var.vercel_team_slug))
    error_message = "vercel_team_slug는 소문자·숫자·하이픈만 쓴다."
  }
}

variable "vercel_project_name" {
  description = "Vercel 프로젝트 이름. 토큰 sub의 project 값이다. 프로젝트 이름을 바꾸면 sub도 바뀌어 역할 전환이 거부된다."
  type        = string
  default     = "vibecoding-project-4"
}

variable "bedrock_region" {
  description = "Bedrock·STS를 부르는 리전. 백엔드 BEDROCK_REGION, infra/의 sts_event_region과 같아야 한다."
  type        = string
  default     = "ap-northeast-1"
}

variable "bedrock_model_id" {
  description = "호출할 기반 모델 ID. 백엔드 BEDROCK_MODEL_ID는 앞에 global.을 붙인 글로벌 추론 프로필 ID다. 둘 중 하나만 바꾸면 AccessDeniedException이 나므로 함께 바꾸고 다시 apply한다."
  type        = string
  default     = "openai.gpt-6-luna"
}
