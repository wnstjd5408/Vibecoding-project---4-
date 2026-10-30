# DB 덤프와 이미지 파일을 보관하는 비공개 S3 버킷과, GitHub Actions 백업 job이 쓰는 역할(MEG-94).
# 버킷 정책과 IAM 역할은 Infra CD apply 역할의 권한 밖이라 이 폴더는 사람이 로컬에서만 apply한다.
#
# 버킷 안 위치:
# - db/<시각>/            주 1회 DB 덤프(roles·schema·data)와 행 수. retention_days 뒤 지운다.
# - glossary-images/<시각>/ 주 1회 사전 이미지. retention_days 뒤 지운다.
# - note-images/<시각>/     Notion 가져오기 직후 1회 노트 이미지. 지우지 않는다(Q11 결정).
# 데이터 덤프에는 auth 스키마(계정·비밀번호 해시)가 들어 있다. 공개 차단과 TLS 강제를 풀지 않는다.

locals {
  bucket_name       = "${var.owner}-cs-learning-db-backup"
  oidc_host         = "token.actions.githubusercontent.com"
  expiring_prefixes = ["db/", "glossary-images/"]
  upload_prefixes   = ["db/", "glossary-images/", "note-images/"]
}

resource "aws_s3_bucket" "backup" {
  bucket = local.bucket_name
}

resource "aws_s3_bucket_public_access_block" "backup" {
  bucket                  = aws_s3_bucket.backup.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "backup" {
  bucket = aws_s3_bucket.backup.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# SSE-S3. KMS 키는 월 요금이 붙어 쓰지 않는다(공용 계정 비용 규칙).
resource "aws_s3_bucket_server_side_encryption_configuration" "backup" {
  bucket = aws_s3_bucket.backup.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "backup" {
  bucket = aws_s3_bucket.backup.id

  dynamic "rule" {
    for_each = local.expiring_prefixes
    content {
      id     = "expire-${trimsuffix(rule.value, "/")}"
      status = "Enabled"
      filter {
        prefix = rule.value
      }
      expiration {
        days = var.retention_days
      }
    }
  }

  # 업로드가 중간에 끊기면 남는 조각도 요금이 붙는다.
  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

data "aws_iam_policy_document" "bucket" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.backup.arn,
      "${aws_s3_bucket.backup.arn}/*",
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "backup" {
  bucket = aws_s3_bucket.backup.id
  policy = data.aws_iam_policy_document.bucket.json

  # 공개 차단을 먼저 걸어 둔 뒤 정책을 붙인다.
  depends_on = [aws_s3_bucket_public_access_block.backup]
}

# infra/github-oidc가 만든 GitHub OIDC 공급자를 그대로 쓴다. 이 폴더는 공급자를 만들거나 지우지 않는다.
data "aws_iam_openid_connect_provider" "github" {
  url = "https://${local.oidc_host}"
}

# 이 저장소의 db-backup Environment에서 온 토큰만 받는다. 브랜치 제한(main만)은 Environment의
# 배포 브랜치 규칙이 맡는다. 사람이 GitHub에서 설정한다(infra/README.md "DB·이미지 백업" 절).
data "aws_iam_policy_document" "trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:sub"
      values   = ["repo:${var.github_subject_repository}:environment:${var.backup_environment}"]
    }
  }
}

# description은 ASCII만 쓴다(한글이면 apply의 CreateRole에서 실패한다, infra/github-oidc 참고).
resource "aws_iam_role" "backup" {
  name                 = "${var.owner}-db-backup"
  description          = "Uploads DB dumps and image backups (GitHub Actions environment ${var.backup_environment})"
  assume_role_policy   = data.aws_iam_policy_document.trust.json
  max_session_duration = 3600
}

# 올리기만 한다. 읽기·지우기·목록 권한이 없어 이 역할이 새도 기존 백업을 받거나 지울 수 없다.
# 같은 키로 덮어쓰는 것은 막지 못한다. 워크플로는 실행마다 새 시각·실행 ID 경로를 쓴다.
data "aws_iam_policy_document" "backup" {
  statement {
    sid       = "UploadBackups"
    actions   = ["s3:PutObject"]
    resources = [for prefix in local.upload_prefixes : "${aws_s3_bucket.backup.arn}/${prefix}*"]
  }
}

resource "aws_iam_role_policy" "backup" {
  name   = "db-backup-upload"
  role   = aws_iam_role.backup.id
  policy = data.aws_iam_policy_document.backup.json
}
