#!/usr/bin/env bash
# Deploy the production Cloud Run service.
# Prerequisites:
#   1. cp env/examples/env.yaml.example env.yaml   (gitignored)
#   2. Fill in DB_PASSWORD, SECRET_KEY, REDIS_URL, TENANT_BASE_DOMAIN in env.yaml
#   3. gcloud auth login && gcloud config set project carnitrack
#   4. Docker daemon running
set -euo pipefail

# Resolve repo root (works when invoked as ./scripts/deploy_prod.sh or bash /abs/path/scripts/deploy_prod.sh)
case "${BASH_SOURCE[0]}" in
  /*) _SCRIPT_DIR="$(dirname "${BASH_SOURCE[0]}")" ;;
  *) _SCRIPT_DIR="$(dirname "$PWD/${BASH_SOURCE[0]}")" ;;
esac
SCRIPT_DIR="$(cd "$_SCRIPT_DIR" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Fail fast if Tailwind/PostCSS cannot build (matches Dockerfile build step).
echo "Building Tailwind CSS..."
make tailwind-build

PROD_ENV_YAML="${1:-env.yaml}"

if [ ! -f "$PROD_ENV_YAML" ]; then
  echo "ERROR: $PROD_ENV_YAML not found."
  echo "Run: cp env/examples/env.yaml.example env.yaml"
  exit 1
fi

IMAGE="europe-west1-docker.pkg.dev/carnitrack/carnitrack-repo/carnitrack-app:latest"

echo "Building image for linux/amd64..."
docker build --platform=linux/amd64 -t "$IMAGE" .

echo "Pushing image..."
docker push "$IMAGE"

echo "Deploying carnitrack-app to Cloud Run..."
gcloud run deploy carnitrack-app \
  --image "$IMAGE" \
  --region europe-west1 \
  --platform managed \
  --allow-unauthenticated \
  --env-vars-file "$PROD_ENV_YAML" \
  --add-cloudsql-instances carnitrack:europe-west1:carnitrack-db-belgium \
  --command="" \
  --args=""

echo ""
echo "Done. Production deployed."
