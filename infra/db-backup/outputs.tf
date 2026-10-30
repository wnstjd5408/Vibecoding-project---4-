# 두 값을 GitHub db-backup Environment의 비밀값(AWS_ROLE_ARN, BACKUP_BUCKET)으로 넣는다.
# 역할 ARN에는 계정 ID가, 버킷 이름에는 owner가 들어 있어 커밋하거나 이슈·PR에 옮기지 않는다.

output "role_arn" {
  description = "GitHub db-backup Environment의 AWS_ROLE_ARN 값"
  value       = aws_iam_role.backup.arn
}

output "bucket_name" {
  description = "GitHub db-backup Environment의 BACKUP_BUCKET 값"
  value       = aws_s3_bucket.backup.bucket
}
