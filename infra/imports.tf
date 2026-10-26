# 콘솔에서 만든 리소스를 상태로 가져온다. 가져오기가 끝난 뒤에 남겨 둬도 다시 가져오지 않는다.

import {
  to = aws_budgets_budget.monthly
  id = "${local.account_id}:cs-learning-monthly"
}

import {
  to = aws_ce_anomaly_monitor.services
  id = "arn:aws:ce::${local.account_id}:anomalymonitor/${var.anomaly_monitor_id}"
}

import {
  to = aws_ce_anomaly_subscription.daily
  id = "arn:aws:ce::${local.account_id}:anomalysubscription/${var.anomaly_subscription_id}"
}

import {
  to = aws_cloudtrail.audit
  id = local.trail_arn
}

import {
  to = aws_s3_bucket.trail_logs
  id = var.cloudtrail_bucket_name
}

import {
  to = aws_s3_bucket_public_access_block.trail_logs
  id = var.cloudtrail_bucket_name
}

import {
  to = aws_s3_bucket_server_side_encryption_configuration.trail_logs
  id = var.cloudtrail_bucket_name
}

import {
  to = aws_s3_bucket_ownership_controls.trail_logs
  id = var.cloudtrail_bucket_name
}

import {
  to = aws_s3_bucket_policy.trail_logs
  id = var.cloudtrail_bucket_name
}
