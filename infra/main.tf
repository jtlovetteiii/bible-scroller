terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.67"
    }
  }
  backend "s3" {
    bucket = "cbc-wilm-agent-private"
    key    = "terraform/terraform.tfstate"
    region = "us-east-1"
  }
}