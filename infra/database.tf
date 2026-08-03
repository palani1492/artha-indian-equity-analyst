resource "aws_db_subnet_group" "database" {
  name       = local.name
  subnet_ids = values(aws_subnet.database)[*].id

  tags = { Name = local.name }
}

resource "aws_security_group" "database" {
  name_prefix = "${local.name}-database-"
  description = "PostgreSQL access from backend tasks only"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "PostgreSQL from backend ECS tasks"
    protocol        = "tcp"
    from_port       = 5432
    to_port         = 5432
    security_groups = [aws_security_group.backend.id]
  }

  egress {
    description = "No initiated egress is expected, but stateful replies require an egress rule"
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle {
    create_before_destroy = true
  }

  tags = { Name = "${local.name}-database" }
}

resource "aws_db_instance" "postgres" {
  identifier = local.name

  engine         = "postgres"
  engine_version = "16.14"
  instance_class = var.database_instance_class

  db_name  = var.database_name
  username = var.database_username
  port     = 5432

  manage_master_user_password = true

  allocated_storage     = var.database_allocated_storage
  max_allocated_storage = var.database_max_allocated_storage
  storage_type          = "gp3"
  storage_encrypted     = true

  db_subnet_group_name   = aws_db_subnet_group.database.name
  vpc_security_group_ids = [aws_security_group.database.id]
  publicly_accessible    = false
  multi_az               = false

  backup_retention_period    = var.database_backup_retention_days
  backup_window              = "18:00-19:00"
  maintenance_window         = "sun:19:00-sun:20:00"
  auto_minor_version_upgrade = true

  deletion_protection   = var.database_deletion_protection
  skip_final_snapshot   = true
  copy_tags_to_snapshot = true

  performance_insights_enabled = false

  lifecycle {
    prevent_destroy = false
  }

  tags = { Name = local.name }
}
