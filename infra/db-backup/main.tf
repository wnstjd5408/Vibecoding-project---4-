# DB 덤프와 이미지 파일을 보관하는 비공개 S3 버킷과, GitHub Actions 백업 job이 쓰는 역할(MEG-94).
# 버킷 정책과 IAM 역할은 Infra CD apply 역할의 권한 밖이라 이 폴더는 사람이 로컬에서만 apply한다.
#
# 버킷 안 위치:
# - db/latest/backup.tar               주 1회 DB 덤프(roles·schema·data)와 표별 행 수. 같은 키에 덮어쓴다.
# - glossary-images/latest/images.tar  주 1회 사전 이미지. 같은 키에 덮어쓴다.
# - note-images/<백업 ID>/images.tar    Notion 가져오기 직후 1회 노트 이미지. 지우지 않는다(Q11 결정).
# 백업 하나를 tar 하나로 묶어 버전 하나가 백업 하나가 되게 한다.
#
# 보관 개수(2026-10-30 Q6 결정, 최근 8개)는 날짜가 아니라 버전 수로 센다. 버전 관리를 켜고 같은 키에
# 덮어쓰면 이전 백업이 이전 버전으로 남고, 수명 주기가 retention_count개를 넘는 이전 버전만 지운다.
# 날짜로 지우면 예약 실행이 멈췄을 때 56일 뒤 백업이 0개가 된다(2026-10-30 코드 리뷰 지적).
# 데이터 덤프에는 auth 스키마(계정·비밀번호 해시)가 들어 있다. 공개 차단과 TLS 강제를 풀지 않는다.

locals {
  bucket_name        = "${var.owner}-cs-learning-db-backup"
  oidc_host          = "token.actions.githubusercontent.com"
  versioned_prefixes = ["db/latest/", "glossary-images/latest/"]
  upload_prefixes    = ["db/latest/", "glossary-images/latest/", "note-images/"]
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

resource "aws_s3_bucket_versioning" "backup" {
  bucket = aws_s3_bucket.backup.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "backup" {
  bucket = aws_s3_bucket.backup.id

  # 현재 버전 1개 + 이전 버전 retention_count - 1개를 남긴다. 그보다 오래된 이전 버전은 이전 버전이 된 지
  # 14일이 지나야 지운다(두 조건을 모두 만족해야 지운다). 짧은 시간에 여러 번 덮어써도 2주 동안은
  # 정상 백업이 남는다. 그래서 평소에는 9~10개가 있다. 현재 버전은 만료시키지 않으므로 실행이 멈춰도
  # 마지막 백업은 남는다.
  dynamic "rule" {
    for_each = local.versioned_prefixes
    content {
      id     = "keep-${replace(trimsuffix(rule.value, "/"), "/", "-")}"
      status = "Enabled"
      filter {
        prefix = rule.value
      }
      noncurrent_version_expiration {
        noncurrent_days           = 14
        newer_noncurrent_versions = var.retention_count - 1
      }
    }
  }

  # 이전 버전이 모두 지워진 삭제 표시는 남길 이유가 없다. 이 역할은 지우지 못해 평소에는 생기지 않는다.
  rule {
    id     = "remove-expired-delete-markers"
    status = "Enabled"
    filter {}
    expiration {
      expired_object_delete_marker = true
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

  # 버전 관리가 켜진 뒤에 규칙을 건다.
  depends_on = [aws_s3_bucket_versioning.backup]
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
# 덮어쓴 백업은 이전 버전으로 남는다. 이 역할로 retention_count번 넘게 덮어써도 밀려난 백업은 14일 동안
# 남는다. 역할은 main 전용 Environment에서만 받을 수 있다.
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
