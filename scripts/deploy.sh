#!/usr/bin/env bash
set -Eeuo pipefail

: "${AWS_REGION:?AWS_REGION is required}"

image_tag="${IMAGE_TAG:-$(git rev-parse --short=12 HEAD)}"
terraform_dir="${TERRAFORM_DIR:-infra}"
aws_account_id="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
frontend_repository="$(terraform -chdir="${terraform_dir}" output -raw frontend_ecr_repository_name)"
backend_repository="$(terraform -chdir="${terraform_dir}" output -raw backend_ecr_repository_name)"
registry="${aws_account_id}.dkr.ecr.${AWS_REGION}.amazonaws.com"

aws ecr get-login-password --region "${AWS_REGION}" | docker login --username AWS --password-stdin "${registry}"

docker build \
  --build-arg NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-}" \
  -f Dockerfile.frontend \
  -t "${registry}/${frontend_repository}:${image_tag}" .
docker build \
  -f backend/Dockerfile \
  -t "${registry}/${backend_repository}:${image_tag}" backend

docker push "${registry}/${frontend_repository}:${image_tag}"
docker push "${registry}/${backend_repository}:${image_tag}"

terraform -chdir="${terraform_dir}" apply -auto-approve \
  -var="image_tag=${image_tag}" \
  -target=aws_ecs_cluster.application \
  -target=aws_ecs_task_definition.backend

export ECS_CLUSTER="$(terraform -chdir="${terraform_dir}" output -raw ecs_cluster_name)"
export BACKEND_TASK_DEFINITION="$(terraform -chdir="${terraform_dir}" output -raw backend_task_definition_arn)"
export ECS_SUBNETS="$(terraform -chdir="${terraform_dir}" output -json ecs_subnet_ids | jq -r 'join(",")')"
export BACKEND_SECURITY_GROUP="$(terraform -chdir="${terraform_dir}" output -raw backend_security_group_id)"
export ECS_ASSIGN_PUBLIC_IP="$(terraform -chdir="${terraform_dir}" output -raw ecs_assign_public_ip)"

bash scripts/run-migrations.sh

terraform -chdir="${terraform_dir}" apply -auto-approve -var="image_tag=${image_tag}"

frontend_service="$(terraform -chdir="${terraform_dir}" output -raw frontend_service_name)"
backend_service="$(terraform -chdir="${terraform_dir}" output -raw backend_service_name)"

aws ecs wait services-stable \
  --region "${AWS_REGION}" \
  --cluster "${ECS_CLUSTER}" \
  --services "${frontend_service}" "${backend_service}"

echo "ECS deployment ${image_tag} is stable"
