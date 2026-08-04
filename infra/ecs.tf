resource "aws_cloudwatch_log_group" "frontend" {
  name              = "/ecs/${local.name}/frontend"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "backend" {
  name              = "/ecs/${local.name}/backend"
  retention_in_days = var.log_retention_days
}

resource "aws_ecs_cluster" "application" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecs_cluster_capacity_providers" "application" {
  cluster_name       = aws_ecs_cluster.application.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }
}

resource "aws_ecs_task_definition" "frontend" {
  family                   = "${local.name}-frontend"
  tags                     = local.common_tags
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.frontend_cpu
  memory                   = var.frontend_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.frontend_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  volume {
    name = "frontend-tmp"
  }

  container_definitions = jsonencode([{
    name                   = "frontend"
    image                  = "${aws_ecr_repository.frontend.repository_url}:${var.image_tag}"
    essential              = true
    readonlyRootFilesystem = true
    portMappings = [{
      name          = "http"
      containerPort = 3000
      hostPort      = 3000
      protocol      = "tcp"
    }]
    environment = [
      { name = "NODE_ENV", value = "production" },
      { name = "NEXT_PUBLIC_API_URL", value = "" }
    ]
    mountPoints = [{
      sourceVolume  = "frontend-tmp"
      containerPath = "/tmp"
      readOnly      = false
    }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.frontend.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "frontend"
      }
    }
  }])
}

resource "aws_ecs_task_definition" "backend" {
  family                   = "${local.name}-backend"
  tags                     = local.common_tags
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.backend_cpu
  memory                   = var.backend_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.backend_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  volume {
    name                = "backend-tmp"
    configure_at_launch = false
  }

  container_definitions = jsonencode([{
    name                   = "backend"
    image                  = "${aws_ecr_repository.backend.repository_url}:${var.image_tag}"
    essential              = true
    readonlyRootFilesystem = true
    portMappings = [{
      name          = "http"
      containerPort = 8000
      hostPort      = 8000
      protocol      = "tcp"
    }]
    environment = [for key, value in merge(local.backend_base_environment, var.backend_environment) : {
      name  = key
      value = value
    }]
    mountPoints = [{
      sourceVolume  = "backend-tmp"
      containerPath = "/tmp"
      readOnly      = false
    }]
    secrets = [
      {
        name      = "DB_USERNAME"
        valueFrom = "${aws_db_instance.postgres.master_user_secret[0].secret_arn}:username::"
      },
      {
        name      = "DB_PASSWORD"
        valueFrom = "${aws_db_instance.postgres.master_user_secret[0].secret_arn}:password::"
      },
      {
        name      = "OPENAI_API_KEY"
        valueFrom = "${aws_secretsmanager_secret.application.arn}:OPENAI_API_KEY::"
      },
      {
        name      = "GEMINI_API_KEY"
        valueFrom = "${aws_secretsmanager_secret.application.arn}:GEMINI_API_KEY::"
      },
      {
        name      = "GOOGLE_CLIENT_ID"
        valueFrom = "${aws_secretsmanager_secret.application.arn}:GOOGLE_CLIENT_ID::"
      },
      {
        name      = "GOOGLE_CLIENT_SECRET"
        valueFrom = "${aws_secretsmanager_secret.application.arn}:GOOGLE_CLIENT_SECRET::"
      },
      {
        name      = "SESSION_SECRET"
        valueFrom = "${aws_secretsmanager_secret.application.arn}:SESSION_SECRET::"
      },
      {
        name      = "ADMIN_EMAILS"
        valueFrom = "${aws_secretsmanager_secret.application.arn}:ADMIN_EMAILS::"
      }
    ]
    healthCheck = {
      command = [
        "CMD",
        "python3",
        "-c",
        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
      ]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 30
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.backend.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "backend"
      }
    }
  }])
}

resource "aws_ecs_service" "frontend" {
  name            = "frontend"
  cluster         = aws_ecs_cluster.application.id
  task_definition = aws_ecs_task_definition.frontend.arn
  desired_count   = var.frontend_desired_count

  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }

  network_configuration {
    subnets          = local.ecs_subnet_ids
    security_groups  = [aws_security_group.frontend.id]
    assign_public_ip = local.assign_public_ip
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.frontend.arn
    container_name   = "frontend"
    container_port   = 3000
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 60
  enable_execute_command             = false
  propagate_tags                     = "SERVICE"

  depends_on = [aws_lb_listener_rule.backend]
}

resource "aws_ecs_service" "backend" {
  name            = "backend"
  cluster         = aws_ecs_cluster.application.id
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = var.backend_desired_count

  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }

  network_configuration {
    subnets          = local.ecs_subnet_ids
    security_groups  = [aws_security_group.backend.id]
    assign_public_ip = local.assign_public_ip
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.backend.arn
    container_name   = "backend"
    container_port   = 8000
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 90
  enable_execute_command             = false
  propagate_tags                     = "SERVICE"

  depends_on = [aws_lb_listener_rule.backend]
}

resource "aws_appautoscaling_target" "frontend" {
  max_capacity       = var.service_max_count
  min_capacity       = var.frontend_desired_count
  resource_id        = "service/${aws_ecs_cluster.application.name}/${aws_ecs_service.frontend.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_target" "backend" {
  max_capacity       = var.service_max_count
  min_capacity       = var.backend_desired_count
  resource_id        = "service/${aws_ecs_cluster.application.name}/${aws_ecs_service.backend.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "frontend_cpu" {
  name               = "${local.name}-frontend-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.frontend.resource_id
  scalable_dimension = aws_appautoscaling_target.frontend.scalable_dimension
  service_namespace  = aws_appautoscaling_target.frontend.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = 70
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

resource "aws_appautoscaling_policy" "backend_cpu" {
  name               = "${local.name}-backend-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.backend.resource_id
  scalable_dimension = aws_appautoscaling_target.backend.scalable_dimension
  service_namespace  = aws_appautoscaling_target.backend.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = 70
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}
