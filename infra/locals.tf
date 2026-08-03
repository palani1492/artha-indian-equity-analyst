locals {
  name                             = "${var.project_name}-${var.environment}"
  availability_zones               = slice(data.aws_availability_zones.available.names, 0, 2)
  ecs_subnet_ids                   = var.enable_nat_gateway ? values(aws_subnet.application)[*].id : values(aws_subnet.public)[*].id
  assign_public_ip                 = var.enable_nat_gateway ? false : true
  scheme                           = "https"
  alb_origin                       = "${local.scheme}://${aws_lb.application.dns_name}"
  application_url                  = coalesce(var.public_base_url, local.alb_origin)
  runtime_permissions_boundary_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/${local.name}-runtime-boundary"

  common_tags = merge(
    {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "Terraform"
    },
    var.tags
  )

  backend_base_environment = {
    APP_ENV              = var.environment
    MARKET_DATA_PROVIDER = "live"
    AI_PROVIDER          = lower(var.ai_provider)
    DB_HOST              = aws_db_instance.postgres.address
    DB_PORT              = tostring(aws_db_instance.postgres.port)
    DB_NAME              = var.database_name
    FRONTEND_URL         = local.application_url
    CORS_ORIGINS         = local.application_url
    GOOGLE_REDIRECT_URI  = "${local.application_url}/api/v1/auth/google/callback"
    AUTH_SUCCESS_URL     = local.application_url
  }
}
