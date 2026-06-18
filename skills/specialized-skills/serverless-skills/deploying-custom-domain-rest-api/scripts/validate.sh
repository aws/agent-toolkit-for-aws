#!/usr/bin/env bash
# Validates the deployed REST API with custom domain.
# Usage: ./validate.sh <custom_domain_name> <api_id> <region>

set -euo pipefail

DOMAIN="$1"
API_ID="$2"
REGION="$3"

echo "=== Validating deployment ==="

echo ""
echo "1. Checking DNS resolution..."
DIG_RESULT=$(dig +short "$DOMAIN" 2>/dev/null || true)
if [ -z "$DIG_RESULT" ]; then
    echo "  WARNING: DNS not yet propagated"
else
    echo "  $DIG_RESULT"
fi

echo ""
echo "2. Checking API Gateway..."
aws apigateway get-rest-api --rest-api-id "$API_ID" --region "$REGION" \
    --query '{Name:name,Id:id,Endpoint:endpointConfiguration.types[0]}' \
    --output table

echo ""
echo "3. Checking custom domain..."
aws apigateway get-domain-name --domain-name "$DOMAIN" --region "$REGION" \
    --query '{Domain:domainName,Regional:regionalDomainName,TLS:securityPolicy}' \
    --output table

echo ""
echo "4. Checking base path mapping..."
aws apigateway get-base-path-mappings --domain-name "$DOMAIN" --region "$REGION" \
    --output table

echo ""
echo "5. Checking Lambda functions..."
for fn in request-authorizer example-function; do
    echo "  $fn:"
    aws lambda get-function --function-name "$fn" --region "$REGION" \
        --query 'Configuration.{State:State,Runtime:Runtime,Handler:Handler}' \
        --output table 2>/dev/null || echo "    NOT FOUND"
done

echo ""
echo "6. Testing API endpoint..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    "https://${DOMAIN}/example?QueryString1=queryValue1" \
    -H "HeaderAuth1: headerValue1" 2>/dev/null || echo "000")

if [ "$HTTP_CODE" = "200" ]; then
    echo "  SUCCESS: API returned 200"
    echo "  Response:"
    curl -s "https://${DOMAIN}/example?QueryString1=queryValue1" -H "HeaderAuth1: headerValue1"
    echo ""
else
    echo "  FAILED: API returned $HTTP_CODE"
    echo "  If 000, DNS may not have propagated yet (can take up to 48 hours)"
fi

echo ""
echo "=== Validation complete ==="
