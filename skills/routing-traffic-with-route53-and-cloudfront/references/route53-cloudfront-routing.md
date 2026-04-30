# Configure Route 53 to Route Traffic to CloudFront Distribution

## Overview

This SOP provides a systematic approach to configure Amazon Route 53 to route traffic to an Amazon CloudFront distribution using a custom domain name. It includes verifying prerequisites, creating hosted zones if needed, configuring alternate domain names (CNAMEs) on the CloudFront distribution, and creating alias records in Route 53.

## Parameters

- **domain_name** (required): The custom domain name to use for routing traffic to CloudFront (e.g., example.com or www.example.com)
- **distribution_id** (required): The CloudFront distribution ID to route traffic to
- **hosted_zone_id** (optional): The Route 53 hosted zone ID for the domain. If not provided, the SOP will search for or create one
- **aws_region** (optional, default: "us-east-1"): The AWS region for Route 53 operations
- **enable_ipv6** (optional, default: true): Whether to create AAAA records for IPv6 support

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt rather than one at a time
- You MUST support multiple input methods including:
  - Direct input: Values provided directly in the conversation
  - Configuration files: JSON or YAML configuration files
- You MUST validate that distribution_id follows AWS CloudFront distribution ID format (E[A-Z0-9]+)
- You MUST validate that domain_name is a valid domain format
- You MUST confirm successful acquisition of all parameters before proceeding

## Steps

### 1. Verify Dependencies

Check for required tools and warn the user if any are missing.

**Constraints:**

- You MUST verify the following tools are available in your context:
  - aws_api_call_aws
- You MUST ONLY check for tool existence and MUST NOT attempt to run the tools because running tools during verification could cause unintended side effects
- You MUST inform the user about any missing tools with a clear message
- You MUST ask if the user wants to proceed anyway despite missing tools
- You MUST respect the user's decision to proceed or abort
- You MUST verify AWS CLI is properly configured with this command:

  ```
  aws sts get-caller-identity
  ```

### 2. Verify CloudFront Distribution

Get the CloudFront distribution details and verify it exists.

**Constraints:**

- You MUST retrieve the distribution configuration using:

  ```
  aws cloudfront get-distribution --id {distribution_id}
  ```

- You MUST extract the distribution domain name from the response
- You MUST check if IPv6 is enabled for the distribution
- You MUST verify the distribution status is "Deployed"
- You MUST inform the user if the distribution is not in "Deployed" status and ask if they want to continue

### 3. Check Alternate Domain Names (CNAMEs)

Verify if the custom domain is already configured as an alternate domain name on the CloudFront distribution.

**Constraints:**

- You MUST check if the domain_name is listed in the distribution's alternate domain names (CNAMEs)
- If the domain is NOT in the CNAMEs list, You MUST inform the user that the domain needs to be added to the distribution
- You MUST provide instructions for adding the domain to the distribution's alternate domain names
- You MUST NOT proceed with Route 53 configuration until the domain is properly configured in CloudFront because Route 53 alias records will not work without proper CNAME configuration

### 4. Configure ACM Certificate

Request and validate an SSL certificate for the custom domain to enable HTTPS.

**Constraints:**

- You MUST inform the user that HTTPS requires an SSL certificate from AWS Certificate Manager
- You MUST request the certificate in the us-east-1 region (required for CloudFront) using:

  ```
  aws acm request-certificate --domain-name {domain_name} --validation-method DNS --region us-east-1
  ```

- You MUST capture the certificate ARN from the response
- You MUST retrieve the DNS validation records using:

  ```
  aws acm describe-certificate --certificate-arn {certificate_arn} --region us-east-1
  ```

- You MUST create the DNS validation records in Route 53 using the hosted zone from step 4
- You MUST wait for certificate validation to complete before proceeding
- You SHOULD inform the user that certificate validation typically takes 5-10 minutes

### 5. Update CloudFront Distribution with Certificate

Configure the CloudFront distribution to use the custom domain and SSL certificate.

**Constraints:**

- You MUST add the domain_name to the distribution's alternate domain names (CNAMEs)
- You MUST configure the SSL certificate in the distribution
- You MUST use the following command to update the distribution:

  ```
  aws cloudfront update-distribution --id {distribution_id} --distribution-config '{
    "CallerReference": "{existing_caller_reference}",
    "Aliases": {
      "Quantity": 1,
      "Items": ["{domain_name}"]
    },
    "ViewerCertificate": {
      "ACMCertificateArn": "{certificate_arn}",
      "SSLSupportMethod": "sni-only",
      "MinimumProtocolVersion": "TLSv1.2_2021"
    }
  }'
  ```

- You MUST preserve all existing distribution configuration while adding the certificate and aliases
- You MUST wait for the distribution update to complete before proceeding

### 6. Find or Create Hosted Zone

Locate the appropriate hosted zone for the domain or create one if needed.

**Constraints:**

- If hosted_zone_id is provided, You MUST verify it exists using:

  ```
  aws route53 get-hosted-zone --id {hosted_zone_id}
  ```

- If hosted_zone_id is not provided, You MUST search for existing hosted zones using:

  ```
  aws route53 list-hosted-zones-by-name --dns-name {domain_name}
  ```

- You MUST determine the appropriate hosted zone based on the domain hierarchy
- You MUST check if found hosted zones are public (not private) because CloudFront only works with public hosted zones
- If no suitable public hosted zone exists, You MUST ask the user if they want to create one
- You MUST create a new hosted zone if requested using:

  ```
  aws route53 create-hosted-zone --name {domain_name} --caller-reference {unique_reference}
  ```

- You MUST extract the hosted zone ID from the response for use in subsequent steps

### 7. Create A Record (IPv4)

Create an alias A record to route IPv4 traffic to the CloudFront distribution.

**Constraints:**

- You MUST determine the record name based on the domain_name and hosted zone
- You MUST create an alias A record using:

  ```
  aws route53 change-resource-record-sets --hosted-zone-id {hosted_zone_id} --change-batch '{
    "Changes": [{
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "{record_name}",
        "Type": "A",
        "AliasTarget": {
          "DNSName": "{distribution_domain_name}",
          "EvaluateTargetHealth": false,
          "HostedZoneId": "Z2FDTNDATAQYW2"
        }
      }
    }]
  }'
  ```

- You MUST use the CloudFront hosted zone ID "Z2FDTNDATAQYW2" for all CloudFront distributions
- You MUST use "UPSERT" action to create or update the record
- You MUST capture the change ID from the response for monitoring

### 8. Create AAAA Record (IPv6)

Create an alias AAAA record to route IPv6 traffic to the CloudFront distribution if IPv6 is enabled.

**Constraints:**

- You MUST check if IPv6 is enabled on the CloudFront distribution from step 2
- If IPv6 is enabled and enable_ipv6 parameter is true, You MUST create an AAAA record using:

  ```
  aws route53 change-resource-record-sets --hosted-zone-id {hosted_zone_id} --change-batch '{
    "Changes": [{
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "{record_name}",
        "Type": "AAAA",
        "AliasTarget": {
          "DNSName": "{distribution_domain_name}",
          "EvaluateTargetHealth": false,
          "HostedZoneId": "Z2FDTNDATAQYW2"
        }
      }
    }]
  }'
  ```

- If IPv6 is not enabled or enable_ipv6 is false, You MUST skip this step and inform the user

### 9. Monitor DNS Propagation

Check the status of the DNS record changes and provide guidance on propagation.

**Constraints:**

- You MUST check the status of each change using:

  ```
  aws route53 get-change --id {change_id}
  ```

- You MUST inform the user that changes generally propagate within 60 seconds
- You MUST provide the user with test commands to verify DNS resolution:

  ```
  nslookup {domain_name}
  dig {domain_name}
  ```

- You SHOULD inform the user that full global propagation can take up to 48 hours

### 10. Verify Configuration

Test the complete setup to ensure traffic is properly routed.

**Constraints:**

- You MUST provide instructions for testing the configuration
- You MUST suggest testing both HTTP and HTTPS if SSL certificates are configured
- You SHOULD recommend testing from multiple locations or using online DNS propagation checkers
- You MUST inform the user about CloudFront cache behavior and potential delays in seeing changes

## Examples

### Example Input

```json
{
  "domain_name": "www.example.com",
  "distribution_id": "E1234567890ABC",
  "aws_region": "us-east-1",
  "enable_ipv6": true
}
```

### Example Output

```
Successfully configured Route 53 to route traffic for www.example.com to CloudFront distribution E1234567890ABC
- Created A record (IPv4): www.example.com -> d111111abcdef8.cloudfront.net
- Created AAAA record (IPv6): www.example.com -> d111111abcdef8.cloudfront.net
- DNS changes are propagating (Change ID: C1234567890ABC)
```

## Troubleshooting

### Domain Not in CloudFront CNAMEs
If the domain is not configured as an alternate domain name in CloudFront, you must add it to the distribution configuration before creating Route 53 records.

### Hosted Zone Not Found
If no hosted zone exists for your domain, you'll need to create one or transfer DNS management to Route 53.

### SSL Certificate Issues
If using HTTPS, ensure you have a valid SSL certificate in AWS Certificate Manager for your domain and it's associated with the CloudFront distribution.

### Private Hosted Zone Issues
CloudFront distributions only work with public hosted zones. If you have a private hosted zone for your domain, you'll need to create a public hosted zone or transfer DNS management to Route 53 for public resolution.

### DNS Propagation Delays
DNS changes can take time to propagate globally. Use multiple DNS checking tools and test from different locations to verify propagation.
