#!/usr/bin/env bash
# Host the Tervik API on Azure: Container Apps for the API, PostgreSQL Flexible
# Server for the database. Sign in first with `az login`. Safe to re-run: each
# step skips what already exists.
#
#   scripts/deploy_azure.sh setup    # database, environment, and the API app
#   scripts/deploy_azure.sh github   # let GitHub Actions deploy on every push to main
#   scripts/deploy_azure.sh domain   # attach api.tervik.in once its DNS records exist
#   scripts/deploy_azure.sh status   # where everything is
#
# Settings come from the environment, with these defaults:
#   AZURE_LOCATION=centralindia  AZURE_RESOURCE_GROUP=tervik  API_DOMAIN=api.tervik.in
#   DASHBOARD_URL=https://www.tervik.in  GITHUB_REPO=dhanvin-ai/Tervik
# Optional, passed to the API as secrets on `setup`: TERVIK_ADMIN_TOKEN (generated
# if unset), ANTHROPIC_API_KEY, GOOGLE_CLIENT_ID/SECRET, GITHUB_CLIENT_ID/SECRET.
set -euo pipefail

LOCATION="${AZURE_LOCATION:-centralindia}"
RG="${AZURE_RESOURCE_GROUP:-tervik}"
ENVIRONMENT="tervik-env"
APP="tervik-api"
IDENTITY="tervik-deployer"
DOMAIN="${API_DOMAIN:-api.tervik.in}"
DASHBOARD="${DASHBOARD_URL:-https://www.tervik.in}"
REPO="${GITHUB_REPO:-dhanvin-ai/Tervik}"
OWNER="$(echo "${REPO%%/*}" | tr '[:upper:]' '[:lower:]')"
IMAGE="ghcr.io/$OWNER/tervik-api:latest"
DATABASE="tervik"
DB_ADMIN="tervikadmin"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
exists() { "$@" >/dev/null 2>&1; }

need_azure() {
  command -v az >/dev/null || { echo "Install the Azure CLI first: brew install azure-cli"; exit 1; }
  az account show >/dev/null 2>&1 || { echo "Sign in first: az login"; exit 1; }
  SUBSCRIPTION="$(az account show --query id -o tsv)"
  TENANT="$(az account show --query tenantId -o tsv)"
  # A stable, globally unique database server name for this subscription.
  DB_SERVER="tervik-db-${SUBSCRIPTION:0:8}"
}

image_is_public() {
  local token
  token="$(curl -fsS "https://ghcr.io/token?scope=repository:$OWNER/tervik-api:pull" 2>/dev/null | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')"
  [ -n "$token" ] && [ "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $token" \
    -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.v2+json' \
    "https://ghcr.io/v2/$OWNER/tervik-api/manifests/latest")" = "200" ]
}

setup() {
  need_azure
  image_is_public || {
    echo "The image $IMAGE isn't publicly available yet."
    echo "1. Push to main (or run the Deploy API workflow) so GitHub Actions builds it."
    echo "2. Make it public: https://github.com/users/$OWNER/packages/container/package/tervik-api"
    echo "   → Package settings → Change visibility → Public."
    exit 1
  }

  say "Preparing the subscription"
  az extension add --name containerapp --upgrade --only-show-errors >/dev/null
  for namespace in Microsoft.App Microsoft.OperationalInsights Microsoft.DBforPostgreSQL Microsoft.ManagedIdentity; do
    az provider register --namespace "$namespace" --wait >/dev/null
  done

  say "Resource group $RG in $LOCATION"
  az group create --name "$RG" --location "$LOCATION" --output none

  local database_url=""
  if exists az postgres flexible-server show --resource-group "$RG" --name "$DB_SERVER"; then
    say "Database server $DB_SERVER already exists"
  else
    say "Database server $DB_SERVER (Burstable B1ms, 32 GB: free for 12 months on Azure for Students)"
    # Upper case, lower case, and digits: Azure's complexity rule, and safe in a URL.
    local password="Tv$(openssl rand -hex 18)Q9"
    az postgres flexible-server create --resource-group "$RG" --name "$DB_SERVER" --location "$LOCATION" \
      --tier Burstable --sku-name Standard_B1ms --storage-size 32 --version 16 \
      --admin-user "$DB_ADMIN" --admin-password "$password" --public-access 0.0.0.0 --yes --output none
    database_url="postgresql://$DB_ADMIN:$password@$DB_SERVER.postgres.database.azure.com:5432/$DATABASE?sslmode=require"
  fi
  exists az postgres flexible-server db show --resource-group "$RG" --server-name "$DB_SERVER" --database-name "$DATABASE" ||
    az postgres flexible-server db create --resource-group "$RG" --server-name "$DB_SERVER" --database-name "$DATABASE" --output none

  if ! exists az containerapp env show --name "$ENVIRONMENT" --resource-group "$RG"; then
    say "Container Apps environment $ENVIRONMENT (logs off, to save credits)"
    az containerapp env create --name "$ENVIRONMENT" --resource-group "$RG" --location "$LOCATION" \
      --logs-destination none --output none
  fi

  if exists az containerapp show --name "$APP" --resource-group "$RG"; then
    say "The API app $APP already exists. To change a setting: az containerapp update --set-env-vars …"
  else
    [ -n "$database_url" ] || { echo "The database server existed before this run, so its password isn't known here. Set DATABASE_URL and run again."; exit 1; }
    database_url="${DATABASE_URL:-$database_url}"
    local admin_token="${TERVIK_ADMIN_TOKEN:-$(openssl rand -hex 32)}"
    local secrets=("database-url=$database_url" "admin-token=$admin_token")
    local env=("DATABASE_URL=secretref:database-url" "TERVIK_ADMIN_TOKEN=secretref:admin-token" "PORT=8000"
               "TERVIK_CORS_ORIGINS=$DASHBOARD,https://${DASHBOARD#https://www.}" "TERVIK_DASHBOARD_URL=$DASHBOARD")
    for pair in "ANTHROPIC_API_KEY:anthropic-api-key" "GOOGLE_CLIENT_ID:google-client-id" "GOOGLE_CLIENT_SECRET:google-client-secret" \
                "GITHUB_CLIENT_ID:github-client-id" "GITHUB_CLIENT_SECRET:github-client-secret"; do
      local name="${pair%%:*}" secret="${pair##*:}"
      if [ -n "${!name:-}" ]; then secrets+=("$secret=${!name}"); env+=("$name=secretref:$secret"); fi
    done
    say "The API app $APP (scales to zero when idle)"
    az containerapp create --name "$APP" --resource-group "$RG" --environment "$ENVIRONMENT" \
      --image "$IMAGE" --target-port 8000 --ingress external \
      --min-replicas 0 --max-replicas 1 --cpu 0.5 --memory 1.0Gi \
      --secrets "${secrets[@]}" --env-vars "${env[@]}" --output none
    [ -n "${TERVIK_ADMIN_TOKEN:-}" ] || {
      say "Administrator token (save it now; it's shown only once)"
      echo "$admin_token"
    }
  fi
  status
}

github() {
  need_azure
  command -v gh >/dev/null || { echo "Install the GitHub CLI first: brew install gh"; exit 1; }
  say "A managed identity GitHub Actions signs in as, allowed to update resources in $RG"
  exists az identity show --name "$IDENTITY" --resource-group "$RG" ||
    az identity create --name "$IDENTITY" --resource-group "$RG" --location "$LOCATION" --output none
  local client principal scope
  client="$(az identity show --name "$IDENTITY" --resource-group "$RG" --query clientId -o tsv)"
  principal="$(az identity show --name "$IDENTITY" --resource-group "$RG" --query principalId -o tsv)"
  scope="$(az group show --name "$RG" --query id -o tsv)"
  [ -n "$(az role assignment list --assignee "$principal" --scope "$scope" --role Contributor --query '[0].id' -o tsv)" ] ||
    az role assignment create --assignee-object-id "$principal" --assignee-principal-type ServicePrincipal \
      --role Contributor --scope "$scope" --output none
  # Trust tokens GitHub issues to workflows on this repository's main branch, and nothing else.
  exists az identity federated-credential show --name github-main --identity-name "$IDENTITY" --resource-group "$RG" ||
    az identity federated-credential create --name github-main --identity-name "$IDENTITY" --resource-group "$RG" \
      --issuer https://token.actions.githubusercontent.com --subject "repo:$REPO:ref:refs/heads/main" \
      --audiences api://AzureADTokenExchange --output none
  say "Repository variables for the Deploy API workflow"
  gh variable set AZURE_CLIENT_ID --repo "$REPO" --body "$client"
  gh variable set AZURE_TENANT_ID --repo "$REPO" --body "$TENANT"
  gh variable set AZURE_SUBSCRIPTION_ID --repo "$REPO" --body "$SUBSCRIPTION"
  gh variable set AZURE_RESOURCE_GROUP --repo "$REPO" --body "$RG"
  gh variable set AZURE_CONTAINER_APP --repo "$REPO" --body "$APP"
  echo "Done. Every push to main that changes apps/api now deploys the API."
}

domain() {
  need_azure
  local fqdn verification
  fqdn="$(az containerapp show --name "$APP" --resource-group "$RG" --query properties.configuration.ingress.fqdn -o tsv)"
  verification="$(az containerapp show --name "$APP" --resource-group "$RG" --query properties.customDomainVerificationId -o tsv)"
  local host="${DOMAIN%%.*}"
  if [ "$(dig +short CNAME "$DOMAIN" | sed 's/\.$//')" != "$fqdn" ] || [ -z "$(dig +short TXT "asuid.$DOMAIN")" ]; then
    say "Add these DNS records for $DOMAIN, then run this again"
    echo "  CNAME  $host        → $fqdn"
    echo "  TXT    asuid.$host  → $verification"
    echo "Remove the old Railway records for $host first (the CNAME and _railway-verify.$host)."
    exit 1
  fi
  say "Attaching $DOMAIN with a free managed certificate"
  [ -n "$(az containerapp hostname list --name "$APP" --resource-group "$RG" --query "[?name=='$DOMAIN'].name" -o tsv)" ] ||
    az containerapp hostname add --hostname "$DOMAIN" --name "$APP" --resource-group "$RG" --output none
  az containerapp hostname bind --hostname "$DOMAIN" --name "$APP" --resource-group "$RG" \
    --environment "$ENVIRONMENT" --validation-method CNAME --output none
  echo "Done: https://$DOMAIN/api/health"
}

status() {
  need_azure
  local fqdn
  fqdn="$(az containerapp show --name "$APP" --resource-group "$RG" --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null || true)"
  say "Status"
  echo "  API app:   ${fqdn:+https://$fqdn}${fqdn:-not created}"
  echo "  Health:    ${fqdn:+$(curl -s --max-time 60 "https://$fqdn/api/health" || echo 'starting…')}"
  echo "  Database:  $DB_SERVER.postgres.database.azure.com"
  echo "  Domain:    https://$DOMAIN"
}

case "${1:-}" in
  setup) setup ;;
  github) github ;;
  domain) domain ;;
  status) status ;;
  *) sed -n '2,19p' "$0"; exit 1 ;;
esac
