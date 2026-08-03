provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  name              = "${var.project_name}-${var.environment}"
  state_bucket_name = coalesce(var.state_bucket_name, "${local.name}-tfstate-${data.aws_caller_identity.current.account_id}")
  oidc_provider_arn = var.create_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : var.existing_github_oidc_provider_arn
  oidc_subject      = coalesce(var.github_oidc_subject, "repo:${var.github_repository}:environment:${var.github_environment}")
}

resource "aws_s3_bucket" "terraform_state" {
  bucket        = local.state_bucket_name
  force_destroy = false
}

resource "aws_s3_bucket_versioning" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyUnencryptedTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.terraform_state.arn,
        "${aws_s3_bucket.terraform_state.arn}/*"
      ]
      Condition = {
        Bool = { "aws:SecureTransport" = "false" }
      }
    }]
  })
}

resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 1 : 0

  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

data "aws_iam_policy_document" "github_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [local.oidc_subject]
    }
  }
}

resource "aws_iam_policy" "runtime_boundary" {
  name        = "${local.name}-runtime-boundary"
  description = "Maximum permissions available to Sentellent runtime roles"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "EcrAuthentication"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "ProjectRuntimeAssets"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "secretsmanager:GetSecretValue"
        ]
        Resource = [
          "arn:aws:ecr:${var.aws_region}:${data.aws_caller_identity.current.account_id}:repository/${local.name}-*",
          "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/ecs/${local.name}/*:*",
          "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${local.name}/*",
          "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:rds!db-*"
        ]
      },
      {
        Sid      = "RunProjectTasks"
        Effect   = "Allow"
        Action   = ["ecs:RunTask"]
        Resource = "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:task-definition/${local.name}-*:*"
      },
      {
        Sid      = "PassProjectRolesToEcs"
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.name}-*"
        Condition = {
          StringEquals = {
            "iam:PassedToService" = "ecs-tasks.amazonaws.com"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role" "github_deploy" {
  name                 = "${local.name}-github-deploy"
  assume_role_policy   = data.aws_iam_policy_document.github_assume_role.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "github_deploy" {
  statement {
    sid    = "TerraformState"
    effect = "Allow"
    actions = [
      "s3:ListBucket"
    ]
    resources = [aws_s3_bucket.terraform_state.arn]
  }

  statement {
    sid    = "TerraformStateObjects"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject"
    ]
    resources = ["${aws_s3_bucket.terraform_state.arn}/${var.environment}/terraform.tfstate*"]
  }

  statement {
    sid    = "RegionalInfrastructure"
    effect = "Allow"
    actions = [
      "application-autoscaling:DeleteScalingPolicy",
      "application-autoscaling:DeregisterScalableTarget",
      "application-autoscaling:DescribeScalableTargets",
      "application-autoscaling:DescribeScalingPolicies",
      "application-autoscaling:PutScalingPolicy",
      "application-autoscaling:RegisterScalableTarget",
      "cloudwatch:DeleteAlarms",
      "cloudwatch:DescribeAlarms",
      "ec2:AllocateAddress",
      "ec2:AssociateAddress",
      "ec2:AssociateRouteTable",
      "ec2:AttachInternetGateway",
      "ec2:AuthorizeSecurityGroupEgress",
      "ec2:AuthorizeSecurityGroupIngress",
      "ec2:CreateInternetGateway",
      "ec2:CreateNatGateway",
      "ec2:CreateRoute",
      "ec2:CreateRouteTable",
      "ec2:CreateSecurityGroup",
      "ec2:CreateSubnet",
      "ec2:CreateTags",
      "ec2:CreateVpc",
      "ec2:DeleteInternetGateway",
      "ec2:DeleteNatGateway",
      "ec2:DeleteRoute",
      "ec2:DeleteRouteTable",
      "ec2:DeleteSecurityGroup",
      "ec2:DeleteSubnet",
      "ec2:DeleteVpc",
      "ec2:Describe*",
      "ec2:DetachInternetGateway",
      "ec2:DisassociateAddress",
      "ec2:DisassociateRouteTable",
      "ec2:ModifySubnetAttribute",
      "ec2:ModifyVpcAttribute",
      "ec2:ReleaseAddress",
      "ec2:RevokeSecurityGroupEgress",
      "ec2:RevokeSecurityGroupIngress",
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:CreateRepository",
      "ecr:DeleteLifecyclePolicy",
      "ecr:DeleteRepository",
      "ecr:DescribeImages",
      "ecr:DescribeImageScanFindings",
      "ecr:DescribeRepositories",
      "ecr:GetAuthorizationToken",
      "ecr:GetDownloadUrlForLayer",
      "ecr:GetLifecyclePolicy",
      "ecr:InitiateLayerUpload",
      "ecr:ListImages",
      "ecr:ListTagsForResource",
      "ecr:PutImage",
      "ecr:PutImageScanningConfiguration",
      "ecr:PutLifecyclePolicy",
      "ecr:StartImageScan",
      "ecr:TagResource",
      "ecr:UntagResource",
      "ecr:UploadLayerPart",
      "ecs:CreateCluster",
      "ecs:CreateService",
      "ecs:DeleteCluster",
      "ecs:DeleteService",
      "ecs:DeregisterTaskDefinition",
      "ecs:DescribeClusters",
      "ecs:DescribeServices",
      "ecs:DescribeTaskDefinition",
      "ecs:DescribeTasks",
      "ecs:ListAccountSettings",
      "ecs:ListAttributes",
      "ecs:ListServices",
      "ecs:ListTagsForResource",
      "ecs:ListTaskDefinitions",
      "ecs:ListTasks",
      "ecs:PutClusterCapacityProviders",
      "ecs:RegisterTaskDefinition",
      "ecs:RunTask",
      "ecs:TagResource",
      "ecs:UntagResource",
      "ecs:UpdateService",
      "elasticloadbalancing:AddTags",
      "elasticloadbalancing:CreateLoadBalancer",
      "elasticloadbalancing:CreateTargetGroup",
      "elasticloadbalancing:DeleteLoadBalancer",
      "elasticloadbalancing:DeleteTargetGroup",
      "elasticloadbalancing:Describe*",
      "elasticloadbalancing:ModifyLoadBalancerAttributes",
      "elasticloadbalancing:ModifyTargetGroup",
      "elasticloadbalancing:ModifyTargetGroupAttributes",
      "elasticloadbalancing:RemoveTags",
      "logs:CreateLogGroup",
      "logs:DeleteLogGroup",
      "logs:DescribeLogGroups",
      "logs:ListTagsForResource",
      "logs:PutRetentionPolicy",
      "logs:TagResource",
      "logs:UntagResource",
      "rds:AddTagsToResource",
      "rds:CreateDBInstance",
      "rds:CreateDBSubnetGroup",
      "rds:DeleteDBInstance",
      "rds:DeleteDBSubnetGroup",
      "rds:Describe*",
      "rds:ListTagsForResource",
      "rds:ModifyDBInstance",
      "rds:ModifyDBSubnetGroup",
      "rds:RemoveTagsFromResource",
      "scheduler:CreateScheduleGroup",
      "scheduler:DeleteScheduleGroup",
      "scheduler:GetScheduleGroup",
      "scheduler:ListScheduleGroups",
      "scheduler:ListSchedules",
      "scheduler:ListTagsForResource",
      "scheduler:TagResource",
      "scheduler:UntagResource",
      "secretsmanager:CreateSecret",
      "wafv2:CreateWebACL",
      "wafv2:DeleteWebACL",
      "wafv2:GetWebACL",
      "wafv2:GetWebACLForResource",
      "wafv2:ListResourcesForWebACL",
      "wafv2:ListTagsForResource",
      "wafv2:ListWebACLs",
      "wafv2:TagResource",
      "wafv2:UntagResource",
      "wafv2:UpdateWebACL"
    ]
    resources = ["*"]

    condition {
      test     = "StringEqualsIfExists"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }
  }

  statement {
    sid    = "ManageProjectApplicationSecret"
    effect = "Allow"
    actions = [
      "secretsmanager:DeleteSecret",
      "secretsmanager:DescribeSecret",
      "secretsmanager:GetResourcePolicy",
      "secretsmanager:GetSecretValue",
      "secretsmanager:ListSecretVersionIds",
      "secretsmanager:PutSecretValue",
      "secretsmanager:TagResource",
      "secretsmanager:UntagResource",
      "secretsmanager:UpdateSecret"
    ]
    resources = ["arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${local.name}/*"]
  }

  statement {
    sid    = "ManageProjectListenersAndSchedules"
    effect = "Allow"
    actions = [
      "elasticloadbalancing:CreateListener",
      "elasticloadbalancing:CreateRule",
      "elasticloadbalancing:DeleteListener",
      "elasticloadbalancing:DeleteRule",
      "elasticloadbalancing:ModifyListener",
      "elasticloadbalancing:ModifyRule",
      "scheduler:CreateSchedule",
      "scheduler:DeleteSchedule",
      "scheduler:GetSchedule",
      "scheduler:UpdateSchedule",
      "wafv2:AssociateWebACL",
      "wafv2:DisassociateWebACL"
    ]
    resources = [
      "arn:aws:elasticloadbalancing:${var.aws_region}:${data.aws_caller_identity.current.account_id}:loadbalancer/app/${local.name}/*",
      "arn:aws:elasticloadbalancing:${var.aws_region}:${data.aws_caller_identity.current.account_id}:targetgroup/${substr(local.name, 0, 23)}-*/*",
      "arn:aws:elasticloadbalancing:${var.aws_region}:${data.aws_caller_identity.current.account_id}:listener/app/${local.name}/*/*",
      "arn:aws:elasticloadbalancing:${var.aws_region}:${data.aws_caller_identity.current.account_id}:listener-rule/app/${local.name}/*/*/*",
      "arn:aws:scheduler:${var.aws_region}:${data.aws_caller_identity.current.account_id}:schedule/${local.name}/*",
      "arn:aws:wafv2:${var.aws_region}:${data.aws_caller_identity.current.account_id}:regional/webacl/${local.name}/*"
    ]
  }

  # Terraform must use wildcard resources for several create APIs because the
  # ARN does not exist yet. An explicit deny makes the regional allow usable
  # only when resources are created with this project's mandatory default tag.
  statement {
    sid    = "DenyUntaggedCreates"
    effect = "Deny"
    actions = [
      "cloudwatch:PutMetricAlarm",
      "ec2:AllocateAddress",
      "ec2:CreateInternetGateway",
      "ec2:CreateNatGateway",
      "ec2:CreateRouteTable",
      "ec2:CreateSecurityGroup",
      "ec2:CreateSubnet",
      "ec2:CreateVpc",
      "ecr:CreateRepository",
      "ecs:CreateCluster",
      "ecs:CreateService",
      "ecs:RegisterTaskDefinition",
      "elasticloadbalancing:CreateLoadBalancer",
      "elasticloadbalancing:CreateTargetGroup",
      "logs:CreateLogGroup",
      "rds:CreateDBInstance",
      "rds:CreateDBSubnetGroup",
      "scheduler:CreateScheduleGroup",
      "secretsmanager:CreateSecret",
      "wafv2:CreateWebACL"
    ]
    resources = ["*"]

    condition {
      test     = "StringNotEqualsIfExists"
      variable = "aws:RequestTag/Project"
      values   = [var.project_name]
    }
  }

  # Prevent the provisioning role from changing or deleting tagged resources
  # belonging to another project. Read-only discovery remains regional so
  # Terraform can resolve dependencies and detect naming conflicts.
  statement {
    sid    = "DenyNonProjectMutations"
    effect = "Deny"
    actions = [
      "cloudwatch:DeleteAlarms",
      "cloudwatch:PutMetricAlarm",
      "ec2:AssociateAddress",
      "ec2:AssociateRouteTable",
      "ec2:AttachInternetGateway",
      "ec2:AuthorizeSecurityGroupEgress",
      "ec2:AuthorizeSecurityGroupIngress",
      "ec2:CreateRoute",
      "ec2:DeleteInternetGateway",
      "ec2:DeleteNatGateway",
      "ec2:DeleteRoute",
      "ec2:DeleteRouteTable",
      "ec2:DeleteSecurityGroup",
      "ec2:DeleteSubnet",
      "ec2:DeleteVpc",
      "ec2:DetachInternetGateway",
      "ec2:DisassociateAddress",
      "ec2:DisassociateRouteTable",
      "ec2:ModifySubnetAttribute",
      "ec2:ModifyVpcAttribute",
      "ec2:ReleaseAddress",
      "ec2:RevokeSecurityGroupEgress",
      "ec2:RevokeSecurityGroupIngress",
      "ecr:DeleteLifecyclePolicy",
      "ecr:DeleteRepository",
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:PutImageScanningConfiguration",
      "ecr:PutLifecyclePolicy",
      "ecr:StartImageScan",
      "ecr:TagResource",
      "ecr:UntagResource",
      "ecr:UploadLayerPart",
      "ecs:DeleteCluster",
      "ecs:DeleteService",
      "ecs:PutClusterCapacityProviders",
      "ecs:RunTask",
      "ecs:TagResource",
      "ecs:UntagResource",
      "ecs:UpdateService",
      "elasticloadbalancing:DeleteLoadBalancer",
      "elasticloadbalancing:DeleteTargetGroup",
      "elasticloadbalancing:ModifyLoadBalancerAttributes",
      "elasticloadbalancing:ModifyTargetGroup",
      "elasticloadbalancing:ModifyTargetGroupAttributes",
      "logs:DeleteLogGroup",
      "logs:PutRetentionPolicy",
      "logs:TagResource",
      "logs:UntagResource",
      "rds:AddTagsToResource",
      "rds:DeleteDBInstance",
      "rds:DeleteDBSubnetGroup",
      "rds:ModifyDBInstance",
      "rds:RemoveTagsFromResource",
      "scheduler:DeleteScheduleGroup",
      "scheduler:TagResource",
      "scheduler:UntagResource",
      "secretsmanager:DeleteSecret",
      "secretsmanager:PutSecretValue",
      "secretsmanager:UpdateSecret",
      "wafv2:DeleteWebACL",
      "wafv2:TagResource",
      "wafv2:UntagResource",
      "wafv2:UpdateWebACL"
    ]
    resources = ["*"]

    condition {
      test     = "StringNotEqualsIfExists"
      variable = "aws:ResourceTag/Project"
      values   = [var.project_name]
    }
  }

  statement {
    sid    = "ManageProjectRoles"
    effect = "Allow"
    actions = [
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:GetRole",
      "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies",
      "iam:PutRolePolicy",
      "iam:GetRolePolicy",
      "iam:DeleteRolePolicy",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:ListRoleTags",
      "iam:PutRolePermissionsBoundary",
      "iam:UpdateAssumeRolePolicy"
    ]
    resources = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.name}-*"]
  }

  statement {
    sid    = "ReadRuntimeBoundary"
    effect = "Allow"
    actions = [
      "iam:GetPolicy",
      "iam:GetPolicyVersion"
    ]
    resources = [aws_iam_policy.runtime_boundary.arn]
  }

  statement {
    sid       = "PassBoundedProjectRoles"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.name}-*"]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com", "scheduler.amazonaws.com"]
    }
  }

  statement {
    sid    = "DenyRolesWithoutRuntimeBoundary"
    effect = "Deny"
    actions = [
      "iam:CreateRole",
      "iam:PutRolePermissionsBoundary"
    ]
    resources = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.name}-*"]

    condition {
      test     = "StringNotEquals"
      variable = "iam:PermissionsBoundary"
      values   = [aws_iam_policy.runtime_boundary.arn]
    }
  }

  statement {
    sid       = "CreateRequiredServiceLinkedRoles"
    effect    = "Allow"
    actions   = ["iam:CreateServiceLinkedRole"]
    resources = ["*"]
    condition {
      test     = "StringLike"
      variable = "iam:AWSServiceName"
      values = [
        "ecs.amazonaws.com",
        "ecs.application-autoscaling.amazonaws.com",
        "rds.amazonaws.com",
        "elasticloadbalancing.amazonaws.com"
      ]
    }
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  name   = "${local.name}-deployment"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy.json
}
