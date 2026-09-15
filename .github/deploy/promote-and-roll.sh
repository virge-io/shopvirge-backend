#!/usr/bin/env bash

set -euo pipefail

: "${SRC_IMAGE:?SRC_IMAGE is required}"
: "${ECR_ENDPOINT:?ECR_ENDPOINT is required}"
: "${ECR_REPOSITORY:?ECR_REPOSITORY is required}"
: "${ECS_CLUSTER:?ECS_CLUSTER is required}"
: "${ECS_SERVICE:?ECS_SERVICE is required}"
AWS_REGION="${AWS_REGION:-eu-central-1}"
DEST="${ECR_ENDPOINT}/${ECR_REPOSITORY}"

wait_for_express_deployment() {
  local deployment_id="$1"
  local started_at
  started_at=$(date +%s)

  while true; do
    local service_json primary_deployment_id rollout_state rollout_reason elapsed
    elapsed=$(($(date +%s) - started_at))
    if [ "${elapsed}" -ge 2700 ]; then
      echo "ECS Express deployment did not finish within 2700s." >&2
      return 1
    fi

    service_json=$(aws ecs describe-services \
      --cluster "${ECS_CLUSTER}" \
      --services "${ECS_SERVICE}" \
      --region "${AWS_REGION}" \
      --output json)
    primary_deployment_id=$(jq -r '.services[0].deployments[]? | select(.status == "PRIMARY") | .id' <<<"${service_json}")
    rollout_state=$(jq -r '.services[0].deployments[]? | select(.status == "PRIMARY") | .rolloutState // "UNKNOWN"' <<<"${service_json}")
    rollout_reason=$(jq -r '.services[0].deployments[]? | select(.status == "PRIMARY") | .rolloutStateReason // ""' <<<"${service_json}")

    if [ "${primary_deployment_id}" != "${deployment_id}" ]; then
      echo "Deployment ${deployment_id} is no longer primary." >&2
      return 1
    fi

    case "${rollout_state}" in
      COMPLETED)
        return 0
        ;;
      FAILED)
        echo "Deployment ${deployment_id} failed: ${rollout_reason}" >&2
        return 1
        ;;
    esac

    sleep 5
  done
}

echo "==> Pulling ${SRC_IMAGE}"
echo "${GHCR_TOKEN:?GHCR_TOKEN is required}" | docker login ghcr.io \
  --username "${GHCR_USER:?GHCR_USER is required}" --password-stdin
docker pull "${SRC_IMAGE}"

echo "==> Pushing ${DEST}:latest and ${DEST}:${EXTRA_TAG:?EXTRA_TAG is required}"
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${ECR_ENDPOINT}"
docker tag "${SRC_IMAGE}" "${DEST}:latest"
docker tag "${SRC_IMAGE}" "${DEST}:${EXTRA_TAG}"
docker push "${DEST}:latest"
docker push "${DEST}:${EXTRA_TAG}"

CURRENT_DEPLOYMENT_ARN=$(aws ecs list-service-deployments \
  --cluster "${ECS_CLUSTER}" \
  --service "${ECS_SERVICE}" \
  --region "${AWS_REGION}" \
  --query 'serviceDeployments[0].serviceDeploymentArn' \
  --output text)

DEPLOYMENT_CONFIGURATION=$(aws ecs describe-service-deployments \
  --service-deployment-arns "${CURRENT_DEPLOYMENT_ARN}" \
  --region "${AWS_REGION}" \
  --query 'serviceDeployments[0].deploymentConfiguration' \
  --output json \
  | jq '.bakeTimeInMinutes = 1 | if .strategy == "CANARY" then .canaryConfiguration.canaryBakeTimeInMinutes = 1 else . end')

echo "==> Triggering deployment"
UPDATE_RESPONSE=$(aws ecs update-service \
  --cluster "${ECS_CLUSTER}" \
  --service "${ECS_SERVICE}" \
  --force-new-deployment \
  --deployment-configuration "${DEPLOYMENT_CONFIGURATION}" \
  --region "${AWS_REGION}" \
  --output json)
DEPLOYMENT_ID=$(jq -r '.service.deployments[] | select(.status == "PRIMARY") | .id' <<<"${UPDATE_RESPONSE}")

echo "==> Waiting for deployment ${DEPLOYMENT_ID}"
wait_for_express_deployment "${DEPLOYMENT_ID}"

echo "Deployment complete"
