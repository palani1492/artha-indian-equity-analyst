resource "aws_scheduler_schedule_group" "application" {
  name = local.name
}

resource "aws_scheduler_schedule" "ingestion" {
  name       = "refresh-followed-stocks"
  group_name = aws_scheduler_schedule_group.application.name
  state      = var.ingestion_schedule_enabled ? "ENABLED" : "DISABLED"

  schedule_expression          = var.ingestion_schedule_expression
  schedule_expression_timezone = "UTC"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_ecs_cluster.application.arn
    role_arn = aws_iam_role.scheduler.arn

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.backend.arn
      launch_type         = "FARGATE"
      task_count          = 1
      platform_version    = "LATEST"

      network_configuration {
        assign_public_ip = local.assign_public_ip
        security_groups  = [aws_security_group.backend.id]
        subnets          = local.ecs_subnet_ids
      }
    }

    input = jsonencode({
      containerOverrides = [{
        name    = "backend"
        command = var.ingestion_command
      }]
    })

    retry_policy {
      maximum_event_age_in_seconds = 3600
      maximum_retry_attempts       = 2
    }
  }
}
