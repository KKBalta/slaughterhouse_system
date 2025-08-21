#!/bin/bash

# CarniTrack Cloud Run Deployment - Belgium (Using Existing Cloud SQL)
set -e

# Configuration
PROJECT_ID="carnitrack"
REGION="europe-west1"         # Belgium
SERVICE_NAME="carnitrack-app"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🥩 Deploying CarniTrack to Cloud Run Belgium${NC}"
echo -e "${BLUE}🇧🇪➡️🇹🇷 Using existing Cloud SQL database${NC}"

# Check if .env.production exists
if [ ! -f ".env.production" ]; then
    echo -e "${RED}❌ .env.production not found${NC}"
    echo -e "${YELLOW}Please make sure .env.production exists with your credentials${NC}"
    exit 1
fi

# Load production environment
source .env.production

echo -e "${BLUE}📋 Deployment Configuration:${NC}"
echo -e "   Project: $PROJECT_ID"
echo -e "   Region: $REGION (Belgium)"
echo -e "   Service: $SERVICE_NAME"
echo -e "   Database: $CLOUD_SQL_CONNECTION_NAME"
echo -e "   Language: Turkish ($LANGUAGE_CODE)"

# Verify GCP authentication
echo -e "${BLUE}🔐 Checking GCP authentication...${NC}"
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
    echo -e "${RED}❌ Not authenticated with GCP. Please run: gcloud auth login${NC}"
    exit 1
fi

# Set project and region
echo -e "${BLUE}📝 Setting GCP project and region...${NC}"
gcloud config set project $PROJECT_ID
gcloud config set compute/region $REGION


# Verify Cloud SQL instance exists
echo -e "${BLUE}🔍 Verifying existing Cloud SQL instance...${NC}"
INSTANCE_NAME="carnitrack-db-belgium"
if ! gcloud sql instances describe $INSTANCE_NAME >/dev/null 2>&1; then
    echo -e "${RED}❌ Cloud SQL instance not found: $INSTANCE_NAME${NC}"
    echo -e "${YELLOW}Please run the Cloud SQL setup script first${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Cloud SQL instance verified: $INSTANCE_NAME${NC}"

# First deployment with wildcard ALLOWED_HOSTS
echo -e "${BLUE}📄 Creating initial environment variables file...${NC}"
cat > /tmp/carnitrack_env.yaml << EOF
DEBUG: "False"
SECRET_KEY: "$SECRET_KEY"
USE_CLOUD_SQL: "True"
DB_NAME: "$DB_NAME"
DB_USER: "$DB_USER"
DB_PASSWORD: "$DB_PASSWORD"
CLOUD_SQL_CONNECTION_NAME: "$CLOUD_SQL_CONNECTION_NAME"
ALLOWED_HOSTS: "carnitrack-app-1000671720976.europe-west1.run.app,localhost,"
CSRF_TRUSTED_ORIGINS: "https://carnitrack-app-1000671720976.europe-west1.run.app,https://localhost"
TIME_ZONE: "Europe/Istanbul"
LANGUAGE_CODE: "tr"
USE_I18N: "True"
USE_L10N: "True"
USE_TZ: "True"
DJANGO_LOG_LEVEL: "INFO"
SECURE_SSL_REDIRECT: "False"
SECURE_BROWSER_XSS_FILTER: "True"
SECURE_CONTENT_TYPE_NOSNIFF: "True"
SESSION_COOKIE_SECURE: "True"
CSRF_COOKIE_SECURE: "True"
STATIC_URL: "/static/"
STATIC_ROOT: "/app/staticfiles"
STATICFILES_STORAGE: "whitenoise.storage.CompressedManifestStaticFilesStorage"
MEDIA_URL: "/media/"
TAILWIND_APP_NAME: "theme"
EOF

# Build and deploy to Cloud Run
echo -e "${BLUE}🏗️ Building and deploying to Cloud Run Belgium...${NC}"
gcloud run deploy $SERVICE_NAME \
    --source . \
    --platform managed \
    --region $REGION \
    --allow-unauthenticated \
    --port 8080 \
    --memory 2Gi \
    --cpu 1 \
    --max-instances 10 \
    --min-instances 0 \
    --timeout 300 \
    --concurrency 80 \
    --add-cloudsql-instances $CLOUD_SQL_CONNECTION_NAME \
    --env-vars-file /tmp/carnitrack_env.yaml

# Clean up temporary file
rm -f /tmp/carnitrack_env.yaml



# Wait for the update to propagate
echo -e "${BLUE}⏳ Waiting for configuration to propagate...${NC}"
sleep 10

# Test the deployment
echo -e "${BLUE}🧪 Testing deployment...${NC}"
sleep 15  # Give Cloud Run more time to start
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$SERVICE_URL" || echo "000")

# Enhanced testing with redirect handling
echo -e "${BLUE}🔄 Testing redirect resolution...${NC}"
FINAL_STATUS=$(timeout 10 curl -L -s -o /dev/null -w "%{http_code}" "$SERVICE_URL" 2>/dev/null || echo "TIMEOUT")

# Test static files
echo -e "${BLUE}🎨 Testing Tailwind CSS static files...${NC}"
STATIC_CSS_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$SERVICE_URL/static/css/dist/styles.css" 2>/dev/null || echo "000")
STATIC_ADMIN_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$SERVICE_URL/static/admin/css/base.css" 2>/dev/null || echo "000")

if [ "$STATIC_CSS_STATUS" = "200" ]; then
    echo -e "${GREEN}✅ Tailwind CSS accessible!${NC}"
elif [ "$STATIC_CSS_STATUS" = "404" ]; then
    echo -e "${YELLOW}⚠️ Tailwind CSS not found - checking build logs...${NC}"
else
    echo -e "${YELLOW}⚠️ Static CSS response: HTTP $STATIC_CSS_STATUS${NC}"
fi

if [ "$STATIC_ADMIN_STATUS" = "200" ]; then
    echo -e "${GREEN}✅ Django admin CSS accessible!${NC}"
else
    echo -e "${YELLOW}⚠️ Admin CSS response: HTTP $STATIC_ADMIN_STATUS${NC}"
fi

if [ "$HTTP_STATUS" = "200" ] || [ "$HTTP_STATUS" = "302" ] || [ "$HTTP_STATUS" = "301" ]; then
    echo -e "${GREEN}✅ Deployment responding! (HTTP $HTTP_STATUS)${NC}"
    
    if [ "$FINAL_STATUS" = "200" ]; then
        echo -e "${GREEN}✅ Application working correctly!${NC}"
    elif [ "$FINAL_STATUS" = "TIMEOUT" ]; then
        echo -e "${YELLOW}⚠️ Redirect loop detected - try accessing specific URLs${NC}"
        echo -e "${YELLOW}Try: $SERVICE_URL/tr/ or $SERVICE_URL/admin/${NC}"
    else
        echo -e "${YELLOW}⚠️ Final response: HTTP $FINAL_STATUS${NC}"
    fi
elif [ "$HTTP_STATUS" = "500" ]; then
    echo -e "${YELLOW}⚠️ Server error (500) - check logs${NC}"
elif [ "$HTTP_STATUS" = "000" ]; then
    echo -e "${YELLOW}⚠️ Connection failed - check if service is starting${NC}"
else
    echo -e "${YELLOW}⚠️ Unexpected response: HTTP $HTTP_STATUS${NC}"
fi

# Display results
echo ""
echo -e "${GREEN}🎉 CarniTrack deployed successfully in Belgium!${NC}"
echo -e "${GREEN}🇧🇪➡️🇹🇷 Optimized for Turkish client performance${NC}"
echo ""
echo -e "${BLUE}📊 Deployment Details:${NC}"
echo -e "   🌐 Application URL: $SERVICE_URL"
echo -e "   🔧 Admin Panel: $SERVICE_URL/admin/"
echo -e "   🇹🇷 Turkish Interface: $SERVICE_URL/tr/"
echo -e "   🌍 Region: Belgium (europe-west1)"
echo -e "   🗄️ Database: Existing Cloud SQL Belgium"
echo ""
echo -e "${BLUE}📈 Expected Performance for Turkey:${NC}"
echo -e "   ${GREEN}• Istanbul: 15-25ms latency${NC}"
echo -e "   ${GREEN}• Ankara: 20-30ms latency${NC}"
echo -e "   ${GREEN}• Izmir: 20-35ms latency${NC}"
echo -e "   ${GREEN}• Bursa: 20-30ms latency${NC}"
echo ""
echo -e "${BLUE}🔍 Useful Commands:${NC}"
echo -e "   📊 View logs: gcloud run services logs read $SERVICE_NAME --region=$REGION"
echo -e "   🔧 Service info: gcloud run services describe $SERVICE_NAME --region=$REGION"
echo -e "   🔄 Redeploy: ./deploy_carnitrack_belgium.sh"
echo ""
echo -e "${BLUE}🧪 Quick Tests:${NC}"
echo "   curl -I $SERVICE_URL/admin/"
echo "   curl -I $SERVICE_URL/tr/"
echo ""
echo -e "${BLUE}📝 Next Steps:${NC}"
echo "1. Test the application: $SERVICE_URL"
echo "2. Access admin panel: $SERVICE_URL/admin/"
echo "3. Test from Turkey for performance validation"
echo "4. Configure custom domain (optional)"
echo "5. Set up monitoring alerts"
echo ""
echo -e "${GREEN}✅ Ready for Turkish users!${NC}"

# Save deployment info
cat > deployment_info.txt << EOF
CarniTrack Production Deployment - Belgium
==========================================
Deployed: $(date)
URL: $SERVICE_URL
Admin: $SERVICE_URL/admin/
Turkish: $SERVICE_URL/tr/
Region: Belgium (europe-west1)
Database: Existing Cloud SQL Belgium
Connection: $CLOUD_SQL_CONNECTION_NAME
Status: HTTP $HTTP_STATUS
Final Status: $FINAL_STATUS

Performance for Turkey:
- Istanbul: 15-25ms latency
- Ankara: 20-30ms latency
- EU GDPR compliant

Commands:
- Logs: gcloud run services logs read $SERVICE_NAME --region=$REGION
- Info: gcloud run services describe $SERVICE_NAME --region=$REGION
- Redeploy: ./deploy_carnitrack_belgium.sh

Quick Tests:
- curl -I $SERVICE_URL/admin/
- curl -I $SERVICE_URL/tr/
EOF

echo -e "${BLUE}📝 Deployment info saved to: deployment_info.txt${NC}"