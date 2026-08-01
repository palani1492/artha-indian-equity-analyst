terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
  }

  # Supply bucket, key, region, and use_lockfile=true via -backend-config.
  backend "s3" {}
}
