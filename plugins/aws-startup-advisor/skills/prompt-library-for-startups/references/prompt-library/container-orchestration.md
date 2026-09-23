---
source_url: https://aws.amazon.com/startups/prompt-library/container-orchestration
title: "Container Orchestration"
tags: ["Auto-Scaling", "Container Orchestration"]
---

## Container Orchestration

Get help creating an AWS EKS-based containerized application deployment for a Node.js app with PostgreSQL database that can auto-scale and handle traffic spikes cost-effectively.

## System Prompt

## Cloud Infrastructure and Deployment Solution Request

## Context

`<context>`
I have an existing containerized application that I want to deploy to AWS using Kubernetes with proper orchestration and auto-scaling. Here's what I need:

Current State:

Docker container running a Node.js web application
Application connects to PostgreSQL database
Currently running locally with docker-compose
Application serves REST API and static frontend

Target Architecture Requirements:

Amazon EKS cluster for Kubernetes orchestration
Horizontal Pod Autoscaler based on CPU/memory usage
Cluster Autoscaler for node scaling
Application Load Balancer for traffic distribution
Managed PostgreSQL database (RDS)
Container registry (ECR) for image storage

Performance & Scaling:

Handle traffic spikes from 10 to 1000 concurrent users
Auto-scale pods between 2-20 replicas
Multi-AZ deployment for high availability
Rolling updates with zero downtime
Health checks and automatic recovery

Cost Optimization:

Use Spot instances for worker nodes where possible
Right-size instances based on actual usage
Implement resource requests and limits
Target monthly cost under $300
Cost monitoring and alerting

Security & Operations:

Network policies for pod-to-pod communication
Secrets management for database credentials
RBAC for cluster access control
Container image vulnerability scanning
Centralized logging with CloudWatch
Monitoring with Prometheus/Grafana or CloudWatch
Deployment & CI/CD:
GitOps workflow preferred
Automated container builds and pushes
Staging and production environments
Rollback capabilities
`</context>`

## Task

Create a comprehensive cloud infrastructure and deployment solution based on the context provided above. Your solution should follow AWS Well-Architected Framework principles (reliability, security, performance efficiency, cost optimization, and operational excellence).

## Required Components

Please provide a complete solution that includes ALL of the following:

1. **Infrastructure as Code**
   - Terraform configuration files for provisioning AWS resources
   - Helm charts for Kubernetes application deployment
   - Detailed explanation of resource configurations and their purposes
2. **Kubernetes Implementation**
   - Complete Kubernetes manifest files (deployments, services, ingress, etc.)
   - Resource requests/limits and scaling configurations
   - Security contexts and network policies
3. **CI/CD Pipeline**
   - Pipeline configuration files (GitHub Actions, Jenkins, AWS CodePipeline, or similar)
   - Build, test, and deployment stages
   - Security scanning and quality gates
4. **Deployment Guide**
   - Prerequisites and environment setup instructions
   - Step-by-step deployment process
   - Validation and testing procedures
   - Rollback procedures

## Requirements

- Ensure all components work together seamlessly
- Implement proper security controls (least privilege, encryption, etc.)
- Include monitoring and logging solutions
- Design for high availability and disaster recovery
- Optimize for cost efficiency
- Readme with full documentation
  Please provide the complete solution with all code snippets, configurations, and instructions formatted properly with appropriate markdown. Include comments in code to explain key decisions and configurations.
  Provide your complete solution immediately without any preamble or additional explanations beyond the requested components.
