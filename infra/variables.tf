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
  type    = number
  default = 1
}

variable "database_deletion_protection" {
  type    = bool
  default = false
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
  default     = ["python", "-m", "app.jobs.ingest", "--all-followed"]
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
