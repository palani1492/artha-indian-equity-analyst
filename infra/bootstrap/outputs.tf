output "state_bucket_name" {
  value = aws_s3_bucket.terraform_state.id
}

output "state_key" {
  value = "${var.environment}/terraform.tfstate"
}

output "github_actions_role_arn" {
  value = aws_iam_role.github_deploy.arn
}

output "github_oidc_provider_arn" {
  value = local.oidc_provider_arn
}

output "runtime_permissions_boundary_arn" {
  value = aws_iam_policy.runtime_boundary.arn
}
