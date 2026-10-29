terraform {
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.70"
    }
  }

  # infra/·infra/github-oidc/와 상태 파일을 나눈다. 버킷 이름과 리전은 커밋하지 않는 ../backend.hcl로 넘긴다.
  backend "s3" {
    key          = "infra/vercel-oidc.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.home_region

  # 공용 실습 계정 규칙: 만드는 모든 리소스에 Owner 태그를 단다.
  default_tags {
    tags = {
      Owner = var.owner
    }
  }
}

data "aws_caller_identity" "current" {}
