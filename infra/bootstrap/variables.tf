variable "project_name" {
  type    = string
  default = "sentellent"
}

variable "environment" {
  type    = string
  default = "production"
}

variable "aws_region" {
  type    = string
  default = "ap-south-1"
}

variable "github_repository" {
  description = "GitHub repository in owner/name form."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must use owner/name form."
  }
}

variable "github_environment" {
  description = "GitHub environment whose OIDC subject may assume the deployment role. Protect it to the configured branch."
  type        = string
  default     = "production"
}

variable "state_bucket_name" {
  description = "Optional globally unique S3 bucket name. A deterministic account-qualified name is used when omitted."
  type        = string
  default     = null
  nullable    = true
}

variable "create_github_oidc_provider" {
  description = "Set false when the account already has token.actions.githubusercontent.com configured."
  type        = bool
  default     = true
}

variable "existing_github_oidc_provider_arn" {
  description = "Existing GitHub Actions OIDC provider ARN when create_github_oidc_provider is false."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.create_github_oidc_provider || var.existing_github_oidc_provider_arn != null
    error_message = "existing_github_oidc_provider_arn is required when provider creation is disabled."
  }
}
