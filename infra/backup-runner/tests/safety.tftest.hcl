# All providers are mocked. These tests NEVER create AWS resources.
mock_provider "aws" {
  mock_data "aws_ssm_parameter" {
    defaults = { value = "ami-00000000000000000" }
  }
  mock_data "aws_availability_zones" {
    defaults = { names = ["ap-northeast-2a"] }
  }
  mock_data "aws_iam_openid_connect_provider" {
    defaults = { arn = "arn:aws:iam::000000000000:oidc-provider/token.actions.githubusercontent.com" }
  }
}

variables {
  owner                   = "test-backup"
  operations_repository   = "example/private-backup"
  operations_oidc_subject = "repo:example/private-backup:ref:refs/heads/main"
}

run "network_storage_and_identity_boundaries" {
  command = apply
  assert {
    condition     = length(aws_security_group.runner.ingress) == 0 && !aws_instance.runner.associate_public_ip_address
    error_message = "No inbound ports or random public IP should be enabled."
  }
  assert {
    condition     = aws_instance.runner.root_block_device[0].encrypted && aws_instance.runner.metadata_options[0].http_tokens == "required" && aws_instance.runner.credit_specification[0].cpu_credits == "standard"
    error_message = "Encryption, IMDSv2 and standard credit mode must remain enabled."
  }
  assert {
    condition     = aws_instance.runner.instance_initiated_shutdown_behavior == "stop" && strcontains(aws_instance.runner.user_data, "OnBootSec=60min")
    error_message = "Cancellation must retain an independent stop timer."
  }
  assert {
    condition     = jsondecode(aws_iam_role.lifecycle.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == var.operations_oidc_subject
    error_message = "Only the exact operations main branch may control the instance."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.lifecycle.policy).Statement[0].Resource == aws_instance.runner.arn
    error_message = "Start/stop must remain limited to this instance."
  }
  assert {
    condition     = !strcontains(aws_iam_role_policy.ssm.policy, "GetParameter") && !strcontains(aws_iam_role_policy.ssm.policy, "s3:")
    error_message = "The host role must not read parameters or backups."
  }
}

run "reject_public_application_repository" {
  command = plan
  variables { operations_repository = "wnstjd5408/Vibecoding-project---4-" }
  expect_failures = [var.operations_repository]
}

run "reject_wildcard_subject" {
  command = plan
  variables { operations_oidc_subject = "repo:example/private-backup:*" }
  expect_failures = [var.operations_oidc_subject]
}
