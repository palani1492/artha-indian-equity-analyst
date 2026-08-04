variable "project_name" {
  description = "Short project identifier used in resource names."
  type        = string
  default     = "sentellent"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,18}[a-z0-9]$", var.project_name))
    error_message = "project_name must be 3-20 lowercase letters, digits, or hyphens."
  }
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
  default     = "production"
}

variable "aws_region" {
  description = "AWS region in which resources are provisioned."
  type        = string
  default     = "ap-south-1"
}

variable "vpc_cidr" {
  description = "CIDR range for the application VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "enable_nat_gateway" {
  description = "Run ECS tasks in private subnets behind one NAT gateway. Disabled by default to avoid fixed NAT cost."
  type        = bool
  default     = false
}

variable "image_tag" {
  description = "Immutable image tag deployed to both services, normally the Git commit SHA."
  type        = string
  default     = "latest"
}

variable "ai_provider" {
  description = "Answer/tagging provider. Gemini and OpenAI require the matching environment secret."
  type        = string
  default     = "local"

  validation {
    condition     = contains(["local", "openai", "gemini"], lower(var.ai_provider))
    error_message = "ai_provider must be local, openai, or gemini."
  }
}

variable "frontend_cpu" {
  type    = number
  default = 256
}

variable "frontend_memory" {
  type    = number
  default = 512
}

variable "backend_cpu" {
  type    = number
  default = 512
}

variable "backend_memory" {
  type    = number
  default = 1024
}

variable "frontend_desired_count" {
  type    = number
  default = 1
}

variable "backend_desired_count" {
  type    = number
  default = 1
}

variable "service_max_count" {
  description = "Maximum count used by target-tracking autoscaling."
  type        = number
  default     = 2
}

variable "database_name" {
  type    = string
  default = "sentellent"
}

variable "database_username" {
  type    = string
  default = "sentellent_admin"
}

variable "database_instance_class" {
  description = "RDS instance class; db.t4g.micro is suitable for a low-traffic challenge deployment."
  type        = string
  default     = "db.t4g.micro"
}

variable "database_allocated_storage" {
  type    = number
  default = 20
}

variable "database_max_allocated_storage" {
  type    = number
  default = 100
}

variable "database_backup_retention_days" {
  description = "Number of days automated RDS backups are retained; production defaults to seven days."
  type        = number
  default     = 7

  validation {
    condition     = var.database_backup_retention_days >= 1 && var.database_backup_retention_days <= 35
    error_message = "database_backup_retention_days must be between 1 and 35 days."
  }
}

variable "database_deletion_protection" {
  description = "Prevent accidental RDS deletion; disable only for an intentional, reviewed teardown."
  type        = bool
  default     = true
}

variable "chat_rate_limit" {
  description = "Maximum chat requests per source IP in a five-minute WAF window."
  type        = number
  default     = 60

  validation {
    condition     = var.chat_rate_limit >= 10
    error_message = "chat_rate_limit must be at least 10 requests per five-minute window."
  }
}

variable "mutation_api_rate_limit" {
  description = "Maximum requests per source IP to the configured expensive or security-sensitive mutation paths in a five-minute WAF window."
  type        = number
  default     = 120

  validation {
    condition     = var.mutation_api_rate_limit >= 10
    error_message = "mutation_api_rate_limit must be at least 10 requests per five-minute window."
  }
}

variable "mutation_api_path_patterns" {
  description = "Anchored AWS WAF regex patterns matched against URI paths for expensive or security-sensitive API operations. Include ^ and $ where an exact path is intended; use a descendant pattern for paths such as /api/v1/stocks/."
  type        = list(string)
  default = [
    "^/api/v1/chat$",
    "^/api/v1/refresh$",
    "^/api/v1/stocks/.*$",
    "^/api/v1/persona$",
    "^/api/v1/notes$",
    "^/api/v1/conversations$",
  ]

  validation {
    condition     = length(var.mutation_api_path_patterns) > 0 && alltrue([for pattern in var.mutation_api_path_patterns : length(trimspace(pattern)) > 0])
    error_message = "mutation_api_path_patterns must contain at least one non-empty AWS WAF regex pattern."
  }
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "certificate_arn" {
  description = "ACM certificate ARN for the canonical production domain."
  type        = string

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:acm:[a-z0-9-]+:[0-9]{12}:certificate/[A-Za-z0-9-]+$", var.certificate_arn))
    error_message = "certificate_arn must be a non-empty ACM certificate ARN."
  }
}

variable "public_base_url" {
  description = "Canonical HTTPS origin (for example https://stocks.example.com) mapped to the ALB."
  type        = string

  validation {
    condition     = can(regex("^https://[^/]+$", var.public_base_url))
    error_message = "public_base_url must be a bare HTTPS origin without a trailing slash."
  }
}

variable "frontend_health_path" {
  type    = string
  default = "/"
}

variable "backend_health_path" {
  type    = string
  default = "/health/ready"
}

variable "alb_idle_timeout_seconds" {
  description = "ALB idle timeout, increased for streamed agent responses."
  type        = number
  default     = 120
}

variable "allowed_ingress_cidrs" {
  description = "CIDRs allowed to reach the public load balancer."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "oauth_callback_rate_limit" {
  description = "Maximum OAuth callback requests per source IP in a five-minute WAF window."
  type        = number
  default     = 100

  validation {
    condition     = var.oauth_callback_rate_limit >= 10
    error_message = "oauth_callback_rate_limit must be at least 10."
  }
}

variable "ingestion_schedule_expression" {
  description = "EventBridge Scheduler expression for news/fundamentals refresh."
  type        = string
  default     = "rate(6 hours)"
}

variable "ingestion_schedule_enabled" {
  type    = bool
  default = true
}

variable "ingestion_command" {
  description = "Backend container command used by the scheduled one-off ingestion task."
  type        = list(string)
  default     = ["-m", "app.jobs.ingest", "--all-followed"]
}

variable "backend_environment" {
  description = "Additional non-secret backend environment variables."
  type        = map(string)
  default     = {}
}

variable "tags" {
  description = "Additional resource tags."
  type        = map(string)
  default     = {}
}
