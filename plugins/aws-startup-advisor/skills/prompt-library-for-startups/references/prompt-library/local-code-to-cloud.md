---
source_url: https://aws.amazon.com/startups/prompt-library/local-code-to-cloud
title: "Local Code to Cloud"
tags: ["Beginner", "Deployment"]
---

## Local Code to Cloud

Get help deploying your local dev environment to AWS with this prompt.

## System Prompt

## AWS Deployment Assistance

## Task

Help me deploy my local development code to AWS in a production-ready manner. I need step-by-step guidance to transition from local development to cloud deployment.

## Current Local Setup

`<development_environment>`
[e.g., Cursor, VS Code, IntelliJ, etc.]
Primary Language/Framework: [e.g., Next.js, Python Flask, Node.js Express, React, etc.]
Local Dependencies: [e.g., PostgreSQL, Redis, MongoDB, etc.]
Development Tools: [e.g., Docker, npm/yarn, pip, etc.]
Current File Structure: [Describe your project organization]
Application Details:
Application Type: [e.g., web app, API, full-stack application, microservice, etc.]
Key Features: [List main functionality - auth, payments, file uploads, etc.]
Database Requirements: [What data you're storing and relationships]
External Integrations: [APIs, services, webhooks you're using]
Static Assets: [Images, CSS, JS bundles, etc.]
Production Requirements:
Expected Users: [e.g., 100 users initially, scaling to 10k over 6 months]
Performance Needs: [e.g., <2s page load, real-time features, etc.]
Availability Requirements: [e.g., 99.9% uptime, maintenance windows acceptable]
Geographic Reach: [e.g., US-only, global, specific regions]
Security Needs: [e.g., user authentication, data encryption, compliance requirements]
Budget & Cost Optimization:
Monthly Budget: [e.g., under $100, $200-500, etc.]
Cost Priorities: [e.g., minimize costs initially, optimize for performance]
Free Tier Usage: [Maximize AWS Free Tier where possible]
Scaling Expectations: [How quickly you expect to grow]
Technical Preferences:
Infrastructure Style: [Serverless preferred, containers acceptable, traditional servers if needed]
Database Preference: [Managed services preferred, specific database requirements]
CI/CD Integration: [Automated deployments from Git, manual deployments acceptable]
Monitoring Needs: [Basic monitoring, comprehensive observability, cost tracking]
Please analyze my local development setup and provide a comprehensive plan to deploy this to AWS following best practices for security, cost optimization, and scalability. Include specific recommendations for AWS services based on my application's actual requirements and usage patterns.
`</development_environment>`

## Instructions

1. Based on my local development environment details above, analyze my current setup and identify the appropriate AWS services for deployment.
2. Provide a clear, structured deployment plan with the following components:
   - Recommended AWS architecture for my specific application type
   - Required AWS services and configurations
   - Step-by-step deployment instructions
   - Security best practices for production deployment
   - Monitoring and maintenance recommendations

## Expected Output Format

Please structure your response as follows:

1. Brief analysis of my current setup
2. Recommended AWS architecture (with justification)
3. Detailed deployment steps
4. Security considerations
5. Post-deployment monitoring and maintenance guidance
6. Readme with documentation
   Provide your complete deployment plan without any preamble or additional explanations beyond the requested information.
