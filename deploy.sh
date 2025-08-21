#!/bin/bash

set -e

# CONFIGURATION
PROJECT_ID="carnitrack"
REGION="europe-west1"
SERVICE_NAME="carnitrack-app"
IMAGE="gcr.io/$PROJECT_ID/$SERVICE_NAME"
ENV_FILE=".env.production"
CLOUDSQL_INSTANCE="carnitrack:europe-west1:carnitrack-db-belgium"

# STEP 1: Validate .env.production exists
if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: $ENV_FILE not found!"
  exit 1
fi

echo "Using environment file: $ENV_FILE"

# STEP 2: Authenticate with GCP
echo "Authenticating with Google Cloud..."
gcloud config set project $PROJECT_ID

# STEP 3: Build Docker image
echo "Building Docker image..."
docker build --platform=linux/amd64 -t $IMAGE .

# STEP 4: Push Docker image to Google Container Registry
echo "Pushing Docker image to Google Container Registry..."
docker push $IMAGE

# STEP 5: Prepare environment variables for Cloud Run
echo "Preparing environment variables for Cloud Run..."
ENV_VARS=$(grep -v '^#' $ENV_FILE | grep -v '^[[:space:]]*$' | grep -v 'CarniTrack Production' | xargs)

# STEP 6: Deploy to Cloud Run
echo "Deploying to Cloud Run..."
gcloud run deploy $SERVICE_NAME \
  --image $IMAGE \
  --region $REGION \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars "$ENV_VARS" \
  --add-cloudsql-instances $CLOUDSQL_INSTANCE

echo "Deployment complete!"
echo "Visit your service at: https://console.cloud.google.com/run/detail/$REGION/$SERVICE_NAME?project=$PROJECT_ID"