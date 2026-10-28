# 이 값을 GitHub Environment 비밀값 AWS_ROLE_ARN에 넣는다. 역할 ARN에는 계정 ID가 있어 커밋하지 않는다.

output "plan_role_arn" {
  description = "infra-plan Environment의 AWS_ROLE_ARN"
  value       = aws_iam_role.plan.arn
}

output "apply_role_arn" {
  description = "infra-apply Environment의 AWS_ROLE_ARN"
  value       = aws_iam_role.apply.arn
}
