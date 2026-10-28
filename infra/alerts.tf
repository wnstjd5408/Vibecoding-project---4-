# 감사 이벤트 알림(MEG-95 3단계). EventBridge 규칙은 같은 리전의 SNS 토픽에만 보낼 수 있어
# 이벤트가 기록되는 리전마다 토픽·구독·규칙을 하나씩 둔다.
# - STS: 백엔드가 STS를 부르는 리전에 기록된다.
# - IAM: 글로벌 서비스라 us-east-1에만 기록된다.

locals {
  audit_alerts = {
    sts_web_identity_failure = {
      region      = var.sts_event_region
      description = "OIDC 역할 전환(AssumeRoleWithWebIdentity) 실패"
      pattern = {
        source        = ["aws.sts"]
        "detail-type" = ["AWS API Call via CloudTrail"]
        detail = {
          eventSource = ["sts.amazonaws.com"]
          eventName   = ["AssumeRoleWithWebIdentity"]
          errorCode   = [{ exists = true }]
        }
      }
    }
    iam_service_credential_created = {
      region      = "us-east-1"
      description = "서비스 전용 자격증명(Bedrock API 키 등) 생성"
      pattern = {
        source        = ["aws.iam"]
        "detail-type" = ["AWS API Call via CloudTrail"]
        detail = {
          eventSource = ["iam.amazonaws.com"]
          eventName   = ["CreateServiceSpecificCredential"]
        }
      }
    }
  }
}

# EventBridge가 AWS 관리형 키(aws/sns)로는 게시하지 못해 토픽 암호화는 켜지 않는다.
resource "aws_sns_topic" "audit_alerts" {
  for_each = local.audit_alerts

  region = each.value.region
  name   = "${var.owner}-cs-learning-audit-alerts"

  # MEG-100: CD로 첫 변경을 적용해 보는 무해한 시험이다. 토픽 동작에는 영향이 없고 콘솔에서 용도를 알아보게 한다.
  tags = {
    Purpose = "audit-alerts"
  }
}

resource "aws_sns_topic_subscription" "audit_alerts_email" {
  for_each = local.audit_alerts

  region    = each.value.region
  topic_arn = aws_sns_topic.audit_alerts[each.key].arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_event_rule" "audit" {
  for_each = local.audit_alerts

  region        = each.value.region
  name          = "${var.owner}-cs-learning-${replace(each.key, "_", "-")}"
  description   = each.value.description
  event_pattern = jsonencode(each.value.pattern)

  # STS 호출은 읽기 전용 관리 이벤트로 분류돼 이 상태여야 규칙에 들어온다.
  # 콘솔에서는 고를 수 없고 CLI·IaC로만 설정된다.
  state = "ENABLED_WITH_ALL_CLOUDTRAIL_MANAGEMENT_EVENTS"
}

resource "aws_cloudwatch_event_target" "audit_sns" {
  for_each = local.audit_alerts

  region    = each.value.region
  rule      = aws_cloudwatch_event_rule.audit[each.key].name
  target_id = "sns"
  arn       = aws_sns_topic.audit_alerts[each.key].arn
}

resource "aws_sns_topic_policy" "audit_alerts" {
  for_each = local.audit_alerts

  region = each.value.region
  arn    = aws_sns_topic.audit_alerts[each.key].arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowEventBridgePublish"
        Effect    = "Allow"
        Principal = { Service = "events.amazonaws.com" }
        Action    = "sns:Publish"
        Resource  = aws_sns_topic.audit_alerts[each.key].arn
        Condition = {
          ArnEquals = { "aws:SourceArn" = aws_cloudwatch_event_rule.audit[each.key].arn }
        }
      },
    ]
  })
}
