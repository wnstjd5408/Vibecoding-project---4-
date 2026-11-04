terraform {
  required_version = ">= 1.11"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.70"
    }
  }
  backend "s3" {
    key          = "infra/backup-runner.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.home_region
  default_tags {
    tags = { Owner = var.owner, Purpose = "private-backup-runner" }
  }
}
