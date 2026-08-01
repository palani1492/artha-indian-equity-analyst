resource "aws_secretsmanager_secret" "application" {
  name                    = "${local.name}/application"
  description             = "Runtime application secrets. Values are seeded out-of-band and never stored in Terraform state."
  recovery_window_in_days = 7
}
