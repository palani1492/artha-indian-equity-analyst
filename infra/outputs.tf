output "application_url" {
  description = "Public application URL. Supply an ACM certificate for HTTPS."
  value       = local.application_url
}

output "load_balancer_dns_name" {
  value = aws_lb.application.dns_name
}

output "frontend_ecr_repository_url" {
  value = aws_ecr_repository.frontend.repository_url
}

output "frontend_ecr_repository_name" {
  value = aws_ecr_repository.frontend.name
}

output "backend_ecr_repository_url" {
  value = aws_ecr_repository.backend.repository_url
}

output "backend_ecr_repository_name" {
  value = aws_ecr_repository.backend.name
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.application.name
}

output "frontend_service_name" {
  value = aws_ecs_service.frontend.name
}

output "backend_service_name" {
  value = aws_ecs_service.backend.name
}

output "backend_task_definition_arn" {
  value = aws_ecs_task_definition.backend.arn
}

output "ecs_subnet_ids" {
  value = local.ecs_subnet_ids
}

output "backend_security_group_id" {
  value = aws_security_group.backend.id
}

output "ecs_assign_public_ip" {
  value = local.assign_public_ip ? "ENABLED" : "DISABLED"
}

output "application_secret_arn" {
  description = "Seed this secret with OPENAI_API_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and SESSION_SECRET before creating ECS services."
  value       = aws_secretsmanager_secret.application.arn
}

output "database_master_secret_arn" {
  description = "AWS-managed RDS master credential secret."
  value       = aws_db_instance.postgres.master_user_secret[0].secret_arn
}

output "database_endpoint" {
  value = aws_db_instance.postgres.endpoint
}

output "frontend_log_group" {
  value = aws_cloudwatch_log_group.frontend.name
}

output "backend_log_group" {
  value = aws_cloudwatch_log_group.backend.name
}

output "waf_web_acl_arn" {
  value = aws_wafv2_web_acl.application.arn
}
