#!/usr/bin/env bash
# Deploy the staging Cloud Run service.
# Prerequisites:
#   1. cp env/examples/env.staging.yaml.example env.staging.yaml   (gitignored)
#   2. Fill in DB_PASSWORD, SECRET_KEY, REDIS_URL/REDIS_SESSION_URL in env.staging.yaml
#   3. gcloud auth login && gcloud config set project carnitrack
#   4. Docker daemon running
#
# First-deploy note:
#   ALLOWED_HOSTS can be a placeholder on first run — Cloud Run will print the real URL.
#   Update env.staging.yaml and re-run this script once you have the URL.
set -euo pipefail

# Repo root (this script lives at repository root)
case "${BASH_SOURCE[0]}" in
  /*) _SCRIPT_DIR="$(dirname "${BASH_SOURCE[0]}")" ;;
  *) _SCRIPT_DIR="$(dirname "$PWD/${BASH_SOURCE[0]}")" ;;
esac
REPO_ROOT="$(cd "$_SCRIPT_DIR" && pwd)"
cd "$REPO_ROOT"

echo "Building Tailwind CSS..."
make tailwind-build

STAGING_ENV_YAML="${1:-env.staging.yaml}"

if [ ! -f "$STAGING_ENV_YAML" ]; then
  echo "ERROR: $STAGING_ENV_YAML not found."
  echo "Run: cp env/examples/env.staging.yaml.example env.staging.yaml"
  exit 1
fi

IMAGE="europe-west1-docker.pkg.dev/carnitrack/carnitrack-repo/carnitrack-app:staging"

echo "Building image for linux/amd64..."
docker build --platform=linux/amd64 -t "$IMAGE" .

echo "Pushing image..."
docker push "$IMAGE"

echo "Deploying carnitrack-app-staging to Cloud Run..."
gcloud run deploy carnitrack-app-staging \
  --image "$IMAGE" \
  --region europe-west1 \
  --platform managed \
  --allow-unauthenticated \
  --env-vars-file "$STAGING_ENV_YAML" \
  --add-cloudsql-instances carnitrack:europe-west1:carnitrack-db-belgium-staging \
  --command="" \
  --args=""

echo ""
echo "Done. Copy the Service URL above into ALLOWED_HOSTS + CSRF_TRUSTED_ORIGINS in $STAGING_ENV_YAML"
echo "then re-run this script if this was the first deploy."
