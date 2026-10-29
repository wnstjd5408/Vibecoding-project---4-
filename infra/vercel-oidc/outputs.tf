# 이 값을 Vercel 환경변수 AWS_ROLE_ARN에 넣는다. 역할 ARN에는 계정 ID가 있어 커밋하거나 이슈·PR에 옮기지 않는다.
# prd → Production, preview → Preview의 Git Branch staging 범위에만 넣는다(Preview 공통값으로 넣지 않는다).

output "role_arns" {
  description = "Vercel AWS_ROLE_ARN 값. 키는 역할 이름 접미사(prd, preview)다."
  value       = { for key, role in aws_iam_role.bedrock : key => role.arn }
}
