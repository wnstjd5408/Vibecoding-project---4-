# MEG-95 2단계에서 콘솔로 만든 감사 트레일과 로그 버킷. imports.tf로 가져온다.
# 트레일·버킷 이름은 바꾸면 새로 만들어져서 owner 접두사 없이 둔다. Owner 태그로 구분한다.

locals {
  account_id = data.aws_caller_identity.current.account_id
  trail_name = "cs-learning-audit"
  trail_arn  = "arn:aws:cloudtrail:${var.home_region}:${local.account_id}:trail/${local.trail_name}"
}

resource "aws_cloudtrail" "audit" {
  name                          = local.trail_name
  s3_bucket_name                = aws_s3_bucket.trail_logs.id
  is_multi_region_trail         = true
  include_global_service_events = true
  enable_log_file_validation    = true

  # 관리 이벤트(읽기·쓰기)만 기록한다. 데이터·Insights 이벤트는 추가 요금이 있어 끈다.
  advanced_event_selector {
    name = "Management events selector"

    field_selector {
      field  = "eventCategory"
      equals = ["Management"]
    }
  }

  depends_on = [aws_s3_bucket_policy.trail_logs]
}

resource "aws_s3_bucket" "trail_logs" {
  bucket = var.cloudtrail_bucket_name

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_public_access_block" "trail_logs" {
  bucket                  = aws_s3_bucket.trail_logs.id
  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "trail_logs" {
  bucket = aws_s3_bucket.trail_logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled       = false
    blocked_encryption_types = ["SSE-C"]
  }
}

resource "aws_s3_bucket_ownership_controls" "trail_logs" {
  bucket = aws_s3_bucket.trail_logs.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# 콘솔이 만든 정책을 그대로 옮겼다. Sid를 바꾸면 plan에 변경이 생긴다.
resource "aws_s3_bucket_policy" "trail_logs" {
  bucket = aws_s3_bucket.trail_logs.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AWSCloudTrailAclCheck20150319-e305f7bd-2034-4e17-b736-628ff3021165"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:GetBucketAcl"
        Resource  = aws_s3_bucket.trail_logs.arn
        Condition = {
          StringEquals = { "AWS:SourceArn" = local.trail_arn }
        }
      },
      {
        Sid       = "AWSCloudTrailWrite20150319-18b0d3c4-f79f-4ce3-b7c9-335036ceec54"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.trail_logs.arn}/AWSLogs/${local.account_id}/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = local.trail_arn
            "s3:x-amz-acl"  = "bucket-owner-full-control"
          }
        }
      },
    ]
  })
}
