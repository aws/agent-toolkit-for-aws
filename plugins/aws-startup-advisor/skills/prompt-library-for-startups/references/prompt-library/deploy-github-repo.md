---
source_url: https://aws.amazon.com/startups/prompt-library/deploy-github-repo
title: "Deploy GitHub Repo"
tags: ["GitHub Integration", "Deployment", "Beginner"]
---

## Deploy GitHub Repo

Have a GitHub repo? This prompt will help you deploy it to AWS.

## System Prompt

## GitHub Repository AWS Deployment Analysis

`<instruction>`
I will analyze the following extracted context and provide a comprehensive response based on its content. Please read the information carefully before proceeding with my analysis.
`</instruction>`
`<context>`
I have an existing GitHub repository that I want to deploy to AWS using the most efficient and cost-effective services. Please analyze my repository and recommend the optimal AWS architecture.
Repository Information:
GitHub URL: [Replace with your actual repository URL]
Primary Language/Framework: [e.g., Node.js, Python Flask, React, etc.]
Application Type: [e.g., web app, API, static site, microservice, etc.]
Current Infrastructure: [Describe any existing Docker, Terraform, CloudFormation, or deployment configs]
Analysis Requirements:
Please analyze my repository and determine:
Application architecture and dependencies
Database requirements (if any)
Static assets and frontend needs
API endpoints and backend services
Existing infrastructure as code (if present)
Build and deployment requirements
Deployment Preferences:
Cost Optimization: Prioritize AWS Free Tier and cost-effective services
Serverless First: Prefer serverless solutions unless specific requirements dictate otherwise
Managed Services: Use AWS managed services to reduce operational overhead
Auto-Scaling: Implement auto-scaling based on demand
Security: Follow AWS security best practices and least privilege access
Performance & Scale Requirements:
Expected Traffic: [e.g., 1000 users/month, 10k requests/day, etc.]
Geographic Distribution: [e.g., US-only, global, specific regions]
Performance Targets: [e.g., <2s page load, 99.9% uptime]
Scaling Needs: [e.g., handle traffic spikes, steady growth expected]
Budget Constraints:
Monthly Budget: [e.g., under $50, $100-200, etc.]
Cost Monitoring: Set up billing alerts and cost tracking
Optimization: Recommend cost optimization strategies
Please provide a comprehensive AWS deployment strategy that maximizes efficiency, minimizes costs, and follows AWS Well-Architected principles. Include specific service recommendations based on my repository's actual structure and requirements.
`</context>`
Based on the extracted context above, I will provide a clear, accurate, and relevant response that directly addresses the information presented. My analysis will be thorough while remaining focused on the key points contained in the context.
Please provide your response based solely on the information in the extracted context, without adding external information or making assumptions beyond what is explicitly stated. Present your answer in a concise format without unnecessary preamble or explanations.
