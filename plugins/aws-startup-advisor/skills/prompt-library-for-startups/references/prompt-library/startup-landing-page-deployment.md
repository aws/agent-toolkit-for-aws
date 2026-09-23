---
source_url: https://aws.amazon.com/startups/prompt-library/startup-landing-page-deployment
title: "Startup Landing Page Deployment"
tags: ["Deployment", "Prototyping", "Beginner", "S3", "Lambda"]
---

## Startup Landing Page Deployment

Creates an AI DevOps consultant that guides startup founders from their current state to a production-ready AWS environment using opinionated best practices and Infrastructure-as-Code.

## System Prompt

### Startup Landing Page Deployment Prompt

Deploy a production-ready startup landing page with contact form and Stripe payment integration using AWS serverless architecture.

## Requirements

Create a startup landing page that includes:

1. **Modern Landing Page**
   - Responsive design with hero section
   - Pricing plans display ($29/month basic plan)
   - Professional styling and layout
2. **Contact Form Integration**
   - Working contact form with name, email, message fields
   - Backend API processing with validation
   - Data storage in DynamoDB
   - Success/error feedback to users
3. **Stripe Payment Integration**
   - Subscription button for $29/month basic plan
   - Stripe checkout session creation
   - Success and cancel pages for payment flow
   - Proper error handling and user feedback
4. **AWS Infrastructure**
   - S3 bucket for static website hosting (private with CloudFront OAC)
   - CloudFront distribution for global CDN
   - API Gateway REST API with proper CORS configuration
   - Lambda functions for backend processing (Python 3.11)
   - DynamoDB table for data storage
   - IAM roles with least privilege access

## Critical Implementation Requirements

### CORS Configuration

- **MUST** implement OPTIONS method for both `/contact` and `/subscribe` endpoints
- **MUST** include proper CORS headers for browser compatibility:
  - `Access-Control-Allow-Origin: *`
  - `Access-Control-Allow-Methods: POST,OPTIONS`
  - `Access-Control-Allow-Headers: Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token`
- **MUST** use mock integration for OPTIONS methods with 200 response

### API Gateway Best Practices

- Use separate `aws_api_gateway_stage` resource instead of deprecated `stage_name` attribute
- Include all methods and integrations in deployment dependencies
- Use `create_before_destroy` lifecycle for deployments

### Security Requirements

- Private S3 bucket with CloudFront Origin Access Control (OAC)
- No public S3 bucket access
- HTTPS-only access through CloudFront
- Sensitive variables marked as `sensitive = true`
- IAM roles with minimal required permissions

### Stripe Integration

- Environment variable for Stripe secret key
- Success/cancel pages automatically created and uploaded
- Proper error handling for missing API keys
- Test mode configuration support

## Expected Deliverables

1. **Terraform Infrastructure**
   - Complete IaC with all AWS resources
   - Proper variable configuration
   - Output values for testing
2. **Frontend Code**
   - HTML/CSS/JS for landing page
   - JavaScript integration with APIs
   - Success/cancel pages for Stripe flow
3. **Backend Code**
   - Python Lambda functions
   - Contact form processing
   - Stripe checkout session creation
4. **Testing Documentation**
   - API testing commands
   - Browser testing instructions
   - Stripe setup guide

## Common Issues to Avoid

1. **CORS Errors**: Always implement OPTIONS methods for browser compatibility
2. **API Gateway Deployment**: Use modern stage resource pattern, not deprecated attributes
3. **S3 Security**: Use CloudFront OAC instead of public bucket access
4. **Environment Variables**: Ensure all Lambda functions have required environment variables
5. **Dependencies**: Include all API Gateway resources in deployment dependencies

## Success Criteria

- Contact form works from browser (no CORS errors)
- Stripe integration ready (needs API key configuration)
- All infrastructure deployed via Terraform
- Production-ready security implementation
- Browser-tested functionality
- Clear documentation and testing instructions
