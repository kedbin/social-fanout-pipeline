#!/bin/bash
#
# Social Fan-Out Pipeline Deployment Script
#
# Deploys all infrastructure components using gcloud CLI.
# Run this script after configuring the variables below.
#
# Prerequisites:
# - gcloud CLI installed and authenticated
# - Billing enabled on your GCP project
# - Owner or Editor role on the project

set -e

# ============================================
# CONFIGURATION - Update these values
# ============================================
PROJECT_ID="your-project-id"
REGION="us-central1"
GITHUB_ORG="your-github-username"
GITHUB_REPO="your-repo-name"

# Resource names (can leave as defaults)
PUBSUB_TOPIC="social-publish-events"
WORKFLOW_NAME="social-fanout-workflow"
SA_NAME="social-fanout-sa"
WIF_POOL="github-pool"
WIF_PROVIDER="github-provider"

# ============================================
# SCRIPT START
# ============================================

echo "Deploying Social Fan-Out Pipeline to $PROJECT_ID"

# Set project
gcloud config set project "$PROJECT_ID"

# Enable required APIs
echo "Enabling APIs..."
gcloud services enable \
  cloudfunctions.googleapis.com \
  workflows.googleapis.com \
  pubsub.googleapis.com \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  logging.googleapis.com \
  secretmanager.googleapis.com \
  eventarc.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com

# Create service account
echo "Creating service account..."
SA_EMAIL="$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"

gcloud iam service-accounts create "$SA_NAME" \
  --display-name="Social Fan-Out Service Account" \
  --description="Service account for social media publishing pipeline" \
  2>/dev/null || echo "Service account already exists"

# Grant necessary roles
echo "Granting IAM roles..."
for role in \
  "roles/cloudfunctions.invoker" \
  "roles/workflows.invoker" \
  "roles/pubsub.publisher" \
  "roles/secretmanager.secretAccessor" \
  "roles/logging.logWriter"
do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="$role" \
    --condition=None \
    --quiet
done

# Create Workload Identity Pool
echo "Setting up Workload Identity Federation..."
gcloud iam workload-identity-pools create "$WIF_POOL" \
  --location="global" \
  --display-name="GitHub Actions Pool" \
  2>/dev/null || echo "Pool already exists"

# Create Workload Identity Provider
gcloud iam workload-identity-pools providers create-oidc "$WIF_PROVIDER" \
  --location="global" \
  --workload-identity-pool="$WIF_POOL" \
  --display-name="GitHub Provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  2>/dev/null || echo "Provider already exists"

# Allow GitHub repo to impersonate service account
gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')/locations/global/workloadIdentityPools/$WIF_POOL/attribute.repository/$GITHUB_ORG/$GITHUB_REPO"

# Create Pub/Sub topic
echo "Creating Pub/Sub topic..."
gcloud pubsub topics create "$PUBSUB_TOPIC" \
  2>/dev/null || echo "Topic already exists"

# Deploy Cloud Functions
echo "Deploying Cloud Functions..."

# LinkedIn function
gcloud functions deploy publish-linkedin \
  --gen2 \
  --runtime=python312 \
  --region="$REGION" \
  --source=./functions/publish-linkedin \
  --entry-point=publish_linkedin \
  --trigger-http \
  --no-allow-unauthenticated \
  --service-account="$SA_EMAIL" \
  --memory=256MB \
  --timeout=60s

# Threads function
gcloud functions deploy publish-threads \
  --gen2 \
  --runtime=python312 \
  --region="$REGION" \
  --source=./functions/publish-threads \
  --entry-point=publish_threads \
  --trigger-http \
  --no-allow-unauthenticated \
  --service-account="$SA_EMAIL" \
  --memory=256MB \
  --timeout=60s

# Deploy Workflow
echo "Deploying Cloud Workflow..."
gcloud workflows deploy "$WORKFLOW_NAME" \
  --location="$REGION" \
  --source=./workflow/workflow.yaml \
  --service-account="$SA_EMAIL"

# Create Eventarc trigger
echo "Creating Eventarc trigger..."
TRIGGER_NAME="social-fanout-trigger"

gcloud eventarc triggers create "$TRIGGER_NAME" \
  --location="$REGION" \
  --destination-workflow="$WORKFLOW_NAME" \
  --destination-workflow-location="$REGION" \
  --event-filters="type=google.cloud.pubsub.topic.v1.messagePublished" \
  --transport-topic="$PUBSUB_TOPIC" \
  --service-account="$SA_EMAIL" \
  2>/dev/null || echo "Trigger already exists"

# Output summary
echo ""
echo "============================================"
echo "Deployment Complete!"
echo "============================================"
echo ""
echo "Workload Identity Provider:"
echo "  projects/$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')/locations/global/workloadIdentityPools/$WIF_POOL/providers/$WIF_PROVIDER"
echo ""
echo "Service Account:"
echo "  $SA_EMAIL"
echo ""
echo "Next steps:"
echo "  1. Add API tokens to Secret Manager:"
echo "     - linkedin-access-token"
echo "     - linkedin-urn"
echo "     - threads-access-token"
echo "     - threads-user-id"
echo ""
echo "  2. Add GitHub Secrets:"
echo "     - GCP_PROJECT_ID: $PROJECT_ID"
echo "     - GCP_WORKLOAD_IDENTITY_PROVIDER: (see above)"
echo "     - GCP_SERVICE_ACCOUNT: $SA_EMAIL"
echo ""
