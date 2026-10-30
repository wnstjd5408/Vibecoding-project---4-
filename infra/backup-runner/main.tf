locals {
  name = "${var.owner}-backup-runner"
}

data "aws_ssm_parameter" "ubuntu" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}
data "aws_availability_zones" "available" {
  state = "available"
}
data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_vpc" "runner" {
  cidr_block           = "10.94.0.0/24"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = local.name }
}
resource "aws_subnet" "runner" {
  vpc_id                  = aws_vpc.runner.id
  cidr_block              = "10.94.0.0/28"
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = false
}
resource "aws_internet_gateway" "runner" {
  vpc_id = aws_vpc.runner.id
}
resource "aws_route_table" "runner" {
  vpc_id = aws_vpc.runner.id
}
resource "aws_route" "internet" {
  route_table_id         = aws_route_table.runner.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.runner.id
}
resource "aws_route_table_association" "runner" {
  subnet_id      = aws_subnet.runner.id
  route_table_id = aws_route_table.runner.id
}
resource "aws_security_group" "runner" {
  name        = local.name
  description = "Outbound backup connections only; administration via SSM"
  vpc_id      = aws_vpc.runner.id
  # No ingress, including SSH. apt HTTP, HTTPS, and Supabase session pooler only.
  dynamic "egress" {
    for_each = toset([80, 443, 5432])
    content {
      from_port   = egress.value
      to_port     = egress.value
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
    }
  }
}

resource "aws_iam_role" "instance" {
  name = local.name
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "ec2.amazonaws.com" } }]
  })
}
resource "aws_iam_role_policy" "ssm" {
  name = "session-manager-only"
  role = aws_iam_role.instance.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ssm:UpdateInstanceInformation", "ssmmessages:CreateControlChannel", "ssmmessages:CreateDataChannel", "ssmmessages:OpenControlChannel", "ssmmessages:OpenDataChannel"]
      Resource = "*"
    }]
  })
}
resource "aws_iam_instance_profile" "runner" {
  name = local.name
  role = aws_iam_role.instance.name
}

resource "aws_instance" "runner" {
  ami                                  = data.aws_ssm_parameter.ubuntu.value
  instance_type                        = "t3.small"
  subnet_id                            = aws_subnet.runner.id
  vpc_security_group_ids               = [aws_security_group.runner.id]
  iam_instance_profile                 = aws_iam_instance_profile.runner.name
  associate_public_ip_address          = false
  instance_initiated_shutdown_behavior = "stop"
  user_data_replace_on_change          = true
  volume_tags                          = { Owner = var.owner, Purpose = "private-backup-runner" }
  user_data = templatefile("${path.module}/bootstrap.sh.tftpl", {
    repository     = var.operations_repository
    runner_version = var.runner_version
    runner_sha256  = var.runner_sha256
  })
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    instance_metadata_tags      = "disabled"
  }
  root_block_device {
    encrypted             = true
    volume_type           = "gp3"
    volume_size           = 16
    delete_on_termination = true
  }
  credit_specification {
    cpu_credits = "standard"
  }
  tags       = { Name = local.name }
  depends_on = [aws_route.internet, aws_route_table_association.runner, aws_iam_role_policy.ssm]
  # Stable AMI until an operator explicitly schedules a replacement/re-registration.
  lifecycle {
    ignore_changes = [ami]
  }
}
resource "aws_eip" "runner" {
  domain = "vpc"
  tags   = { Name = local.name }
}
resource "aws_eip_association" "runner" {
  instance_id   = aws_instance.runner.id
  allocation_id = aws_eip.runner.id
}

resource "aws_iam_role" "lifecycle" {
  name = "${local.name}-lifecycle"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow", Action = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = data.aws_iam_openid_connect_provider.github.arn }
      Condition = { StringEquals = {
        "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        "token.actions.githubusercontent.com:sub" = var.operations_oidc_subject
      } }
    }]
  })
}
resource "aws_iam_role_policy" "lifecycle" {
  name = "start-stop-one-runner"
  role = aws_iam_role.lifecycle.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["ec2:StartInstances", "ec2:StopInstances"], Resource = aws_instance.runner.arn },
      { Effect = "Allow", Action = ["ec2:DescribeInstances", "ec2:DescribeInstanceStatus"], Resource = "*", Condition = { StringEquals = { "aws:RequestedRegion" = var.home_region } } }
    ]
  })
}
