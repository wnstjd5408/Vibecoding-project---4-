# MEG-95 1단계에서 콘솔로 만든 월 예산과 비용 이상 탐지. imports.tf로 가져온다.
# 예산·구독 이름은 바꾸면 새로 만들어져서 owner 접두사 없이 둔다. Owner 태그로 구분한다.

resource "aws_budgets_budget" "monthly" {
  name              = "cs-learning-monthly"
  budget_type       = "COST"
  limit_amount      = var.monthly_budget_usd
  limit_unit        = "USD"
  time_unit         = "MONTHLY"
  time_period_start = var.budget_start
  metrics           = ["UnblendedCost"]

  # 콘솔이 기본 결제 보기를 저장했다. 비워 두면 가져온 뒤 plan이 이 값을 지우려 한다.
  billing_view_arn = "arn:aws:billing::${local.account_id}:billingview/primary"

  # 크레딧·환불을 빼고 실제 사용액만 센다.
  filter_expression {
    not {
      dimensions {
        key    = "RECORD_TYPE"
        values = ["Credit", "Refund"]
      }
    }
  }

  notification {
    notification_type          = "ACTUAL"
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    notification_type          = "ACTUAL"
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    notification_type          = "ACTUAL"
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    notification_type          = "FORECASTED"
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = [var.alert_email]
  }
}

resource "aws_ce_anomaly_monitor" "services" {
  # 콘솔에서 구독 이름(Daily summaries)이 모니터 이름으로 잘못 저장돼 있던 것을 고친다.
  name              = "${var.owner}-cs-learning-cost-monitor"
  monitor_type      = "DIMENSIONAL"
  monitor_dimension = "SERVICE"
}

resource "aws_ce_anomaly_subscription" "daily" {
  name             = "daily-cost-anomaly"
  frequency        = "DAILY"
  monitor_arn_list = [aws_ce_anomaly_monitor.services.arn]

  subscriber {
    type    = "EMAIL"
    address = var.alert_email
  }

  threshold_expression {
    dimension {
      key           = "ANOMALY_TOTAL_IMPACT_ABSOLUTE"
      match_options = ["GREATER_THAN_OR_EQUAL"]
      values        = ["3"]
    }
  }
}
