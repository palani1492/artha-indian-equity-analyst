#!/usr/bin/env bash
set -Eeuo pipefail

: "${AWS_REGION:?AWS_REGION is required}"
: "${ECS_CLUSTER:?ECS_CLUSTER is required}"
: "${BACKEND_TASK_DEFINITION:?BACKEND_TASK_DEFINITION is required}"
: "${ECS_SUBNETS:?ECS_SUBNETS is required (comma-separated IDs)}"
: "${BACKEND_SECURITY_GROUP:?BACKEND_SECURITY_GROUP is required}"

network_configuration="awsvpcConfiguration={subnets=[${ECS_SUBNETS}],securityGroups=[${BACKEND_SECURITY_GROUP}],assignPublicIp=${ECS_ASSIGN_PUBLIC_IP:-ENABLED}}"
task_arn="$(aws ecs run-task \
  --region "${AWS_REGION}" \
  --cluster "${ECS_CLUSTER}" \
  --task-definition "${BACKEND_TASK_DEFINITION}" \
  --launch-type FARGATE \
  --network-configuration "${network_configuration}" \
  --overrides '{"containerOverrides":[{"name":"backend","command":["alembic","upgrade","head"]}]}' \
  --query 'tasks[0].taskArn' \
  --output text)"

if [[ -z "${task_arn}" || "${task_arn}" == "None" ]]; then
  echo "ECS did not return a migration task ARN" >&2
  exit 1
fi

echo "Waiting for migration task ${task_arn}"
aws ecs wait tasks-stopped --region "${AWS_REGION}" --cluster "${ECS_CLUSTER}" --tasks "${task_arn}"

exit_code="$(aws ecs describe-tasks \
  --region "${AWS_REGION}" \
  --cluster "${ECS_CLUSTER}" \
  --tasks "${task_arn}" \
  --query 'tasks[0].containers[?name==`backend`].exitCode | [0]' \
  --output text)"

if [[ "${exit_code}" != "0" ]]; then
  reason="$(aws ecs describe-tasks \
    --region "${AWS_REGION}" \
    --cluster "${ECS_CLUSTER}" \
    --tasks "${task_arn}" \
    --query 'tasks[0].containers[?name==`backend`].reason | [0]' \
    --output text)"
  echo "Migration failed with exit code ${exit_code}: ${reason}" >&2
  exit 1
fi

echo "Database migrations completed"
