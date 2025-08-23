docker build --platform=linux/amd64 \
  -t europe-west1-docker.pkg.dev/carnitrack/carnitrack-repo/carnitrack-app .

docker push europe-west1-docker.pkg.dev/carnitrack/carnitrack-repo/carnitrack-app

gcloud run deploy carnitrack-app \
  --image europe-west1-docker.pkg.dev/carnitrack/carnitrack-repo/carnitrack-app \
  --region europe-west1 \
  --platform managed \
  --allow-unauthenticated \
  --env-vars-file env.yaml \
  --add-cloudsql-instances carnitrack:europe-west1:carnitrack-db-belgium
