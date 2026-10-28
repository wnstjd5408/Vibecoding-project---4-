# infra/ 변경을 GitHub Actions CD로 적용하기 위한 AWS 쪽 신뢰 설정(MEG-100).
# CD가 자기 역할을 만들거나 고칠 수 없게 infra/와 분리했다. 이 폴더는 사람이 로컬에서만 apply한다.
#
# 역할 두 개:
# - plan 역할: 읽기만 한다. plan 파일을 상태 버킷의 plans/ 아래에 올린다. 상태 파일은 못 쓴다.
# - apply 역할: 승인 Environment에서만 받을 수 있다. infra/가 관리하는 리소스만 바꿀 수 있고,
#   IAM 쓰기 권한과 트레일·로그 버킷 삭제 권한은 없다.

locals {
  account_id = data.aws_caller_identity.current.account_id
  oidc_host  = "token.actions.githubusercontent.com"

  # infra/가 관리하는 리소스의 이름. infra/budget.tf, cloudtrail.tf, alerts.tf와 같아야 한다.
  budget_arn      = "arn:aws:budgets::${local.account_id}:budget/cs-learning-monthly"
  trail_arn       = "arn:aws:cloudtrail:${var.home_region}:${local.account_id}:trail/cs-learning-audit"
  log_bucket_arn  = "arn:aws:s3:::${var.cloudtrail_bucket_name}"
  anomaly_arns    = ["arn:aws:ce::${local.account_id}:anomalymonitor/*", "arn:aws:ce::${local.account_id}:anomalysubscription/*"]
  sns_topic_arn   = "arn:aws:sns:*:${local.account_id}:${var.owner}-cs-learning-audit-alerts"
  event_rule_arn  = "arn:aws:events:*:${local.account_id}:rule/${var.owner}-cs-learning-*"
  state_bucket    = "arn:aws:s3:::${var.state_bucket_name}"
  state_object    = "${local.state_bucket}/infra/terraform.tfstate"
  state_lock      = "${local.state_bucket}/infra/terraform.tfstate.tflock"
  plan_objects    = "${local.state_bucket}/plans/*"
  plan_role_name  = "${var.owner}-infra-plan"
  apply_role_name = "${var.owner}-infra-apply"
}

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://${local.oidc_host}"
  client_id_list = ["sts.amazonaws.com"]
}

# 신뢰 정책: 이 저장소의 지정한 Environment에서 온 토큰만 받는다.
# Environment 없이 도는 job이나 다른 저장소의 토큰은 sub가 달라서 거부된다.
# 브랜치 제한은 Environment의 배포 브랜치 규칙(main만)이 맡는다. 사람이 GitHub에서 설정한다.
data "aws_iam_policy_document" "trust" {
  for_each = {
    plan  = var.plan_environment
    apply = var.apply_environment
  }

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:sub"
      values   = ["repo:${var.github_repository}:environment:${each.value}"]
    }
  }
}

resource "aws_iam_role" "plan" {
  name               = local.plan_role_name
  description        = "infra/ plan용 읽기 전용 역할(GitHub Actions ${var.plan_environment})"
  assume_role_policy = data.aws_iam_policy_document.trust["plan"].json
}

resource "aws_iam_role" "apply" {
  name               = local.apply_role_name
  description        = "infra/ apply용 역할(GitHub Actions ${var.apply_environment}, 필수 승인자)"
  assume_role_policy = data.aws_iam_policy_document.trust["apply"].json
}

# 두 역할이 공통으로 쓰는 읽기 권한. terraform plan의 refresh가 관리 대상을 읽는다.
data "aws_iam_policy_document" "read" {
  statement {
    sid       = "ReadBudget"
    actions   = ["budgets:ViewBudget", "budgets:ListTagsForResource"]
    resources = [local.budget_arn]
  }

  # 이상 탐지 조회 API는 리소스 단위 제한을 지원하지 않는다.
  statement {
    sid       = "ReadCostAnomaly"
    actions   = ["ce:GetAnomalyMonitors", "ce:GetAnomalySubscriptions", "ce:ListTagsForResource"]
    resources = ["*"]
  }

  statement {
    sid       = "ReadTrailList"
    actions   = ["cloudtrail:DescribeTrails", "cloudtrail:ListTrails"]
    resources = ["*"]
  }

  statement {
    sid = "ReadTrail"
    actions = [
      "cloudtrail:GetTrail",
      "cloudtrail:GetTrailStatus",
      "cloudtrail:GetEventSelectors",
      "cloudtrail:GetInsightSelectors",
      "cloudtrail:ListTags",
    ]
    resources = [local.trail_arn]
  }

  statement {
    sid = "ReadLogBucket"
    actions = [
      "s3:ListBucket",
      "s3:GetBucket*",
      "s3:GetEncryptionConfiguration",
      "s3:GetLifecycleConfiguration",
      "s3:GetReplicationConfiguration",
      "s3:GetAccelerateConfiguration",
    ]
    resources = [local.log_bucket_arn]
  }

  statement {
    sid       = "ReadAlertTopics"
    actions   = ["sns:GetTopicAttributes", "sns:ListTagsForResource", "sns:ListSubscriptionsByTopic"]
    resources = [local.sns_topic_arn]
  }

  statement {
    sid       = "ReadAlertSubscriptions"
    actions   = ["sns:GetSubscriptionAttributes"]
    resources = ["${local.sns_topic_arn}:*"]
  }

  statement {
    sid       = "ReadAlertRules"
    actions   = ["events:DescribeRule", "events:ListTargetsByRule", "events:ListTagsForResource"]
    resources = [local.event_rule_arn]
  }

  # 상태 버킷: init이 객체를 나열하므로 ListBucket은 버킷 단위로 준다.
  statement {
    sid       = "StateBucketList"
    actions   = ["s3:ListBucket"]
    resources = [local.state_bucket]
  }
}

data "aws_iam_policy_document" "plan" {
  source_policy_documents = [data.aws_iam_policy_document.read.json]

  statement {
    sid       = "StateRead"
    actions   = ["s3:GetObject"]
    resources = [local.state_object]
  }

  # use_lockfile 잠금 파일. plan도 잠금을 잡는다.
  statement {
    sid       = "StateLock"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [local.state_lock]
  }

  # plan 파일은 apply가 내려받는다. 상태 파일은 쓸 수 없다.
  statement {
    sid       = "PlanFileUpload"
    actions   = ["s3:PutObject"]
    resources = [local.plan_objects]
  }
}

data "aws_iam_policy_document" "apply" {
  source_policy_documents = [data.aws_iam_policy_document.read.json]

  statement {
    sid       = "StateReadWrite"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = [local.state_object]
  }

  statement {
    sid       = "StateLock"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [local.state_lock]
  }

  # 적용한 plan 파일을 내려받고 지운다.
  statement {
    sid       = "PlanFileDownloadDelete"
    actions   = ["s3:GetObject", "s3:DeleteObject"]
    resources = [local.plan_objects]
  }

  # 예산 API는 만들기·고치기·지우기에 ModifyBudget 하나를 쓴다.
  statement {
    sid       = "WriteBudget"
    actions   = ["budgets:ModifyBudget", "budgets:TagResource", "budgets:UntagResource"]
    resources = [local.budget_arn]
  }

  statement {
    sid = "WriteCostAnomaly"
    actions = [
      "ce:CreateAnomalyMonitor",
      "ce:UpdateAnomalyMonitor",
      "ce:DeleteAnomalyMonitor",
      "ce:CreateAnomalySubscription",
      "ce:UpdateAnomalySubscription",
      "ce:DeleteAnomalySubscription",
      "ce:TagResource",
      "ce:UntagResource",
    ]
    resources = local.anomaly_arns
  }

  # 감사 트레일은 설정 변경만 허용한다. 삭제·로깅 중지는 사람이 한다.
  statement {
    sid = "WriteTrail"
    actions = [
      "cloudtrail:UpdateTrail",
      "cloudtrail:PutEventSelectors",
      "cloudtrail:StartLogging",
      "cloudtrail:AddTags",
      "cloudtrail:RemoveTags",
    ]
    resources = [local.trail_arn]
  }

  # 로그 버킷도 설정 변경만 허용한다. 버킷·정책 삭제는 사람이 한다.
  statement {
    sid = "WriteLogBucket"
    actions = [
      "s3:PutBucketPolicy",
      "s3:PutEncryptionConfiguration",
      "s3:PutBucketPublicAccessBlock",
      "s3:PutBucketOwnershipControls",
      "s3:PutBucketTagging",
    ]
    resources = [local.log_bucket_arn]
  }

  statement {
    sid = "WriteAlertTopics"
    actions = [
      "sns:CreateTopic",
      "sns:DeleteTopic",
      "sns:SetTopicAttributes",
      "sns:Subscribe",
      "sns:Unsubscribe",
      "sns:SetSubscriptionAttributes",
      "sns:TagResource",
      "sns:UntagResource",
    ]
    resources = [local.sns_topic_arn, "${local.sns_topic_arn}:*"]
  }

  statement {
    sid = "WriteAlertRules"
    actions = [
      "events:PutRule",
      "events:DeleteRule",
      "events:EnableRule",
      "events:DisableRule",
      "events:PutTargets",
      "events:RemoveTargets",
      "events:TagResource",
      "events:UntagResource",
    ]
    resources = [local.event_rule_arn]
  }
}

resource "aws_iam_role_policy" "plan" {
  name   = "infra-plan"
  role   = aws_iam_role.plan.id
  policy = data.aws_iam_policy_document.plan.json
}

resource "aws_iam_role_policy" "apply" {
  name   = "infra-apply"
  role   = aws_iam_role.apply.id
  policy = data.aws_iam_policy_document.apply.json
}
