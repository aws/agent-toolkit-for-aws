---
source_url: https://aws.amazon.com/startups/prompt-library/cost-optimized-eks-with-spot-instances
title: "Karpenter + KEDA: Cost-Optimized EKS with Spot Instances"
tags: ["Cost Optimization", "Deployment", "Advanced", "EKS", "EC2"]
---

## Karpenter + KEDA: Cost-Optimized EKS with Spot Instances

Deploy production-ready EKS with Karpenter auto-scaling, KEDA pod management, and Spot instance prioritization. Includes Bottlerocket OS, encryption, and multi-AZ high availability—optimized for cost.

## System Prompt

Deploy Cost-Optimized Karpenter on EKS with Bottlerocket, Spot Instances, and KEDA

Act as a DevOps engineer and help me deploy Karpenter on an EKS cluster with the following requirements:

Cluster Elasticity & Scaling:

Configure Karpenter to make the cluster as elastic as possible
Set up KEDA to manage pod scaling based on CPU usage
Karpenter should handle node provisioning based on pod demands
Node Provisioning Strategy:

Provision general-purpose nodes only
Prioritize Spot instances and check Spot availability first
Fall back to On-Demand instances only when Spot is unavailable
Enable consolidation for cost optimization
Security & Hardening:

Use Bottlerocket OS for all nodes
Disable SSH access completely
Enable EBS volume encryption
High Availability:

Deploy across multiple availability zones to maximize Spot availability
Implementation:

Use Terraform with the official EKS module to provision the EKS cluster infrastructure
Use kubectl to connect to the Kubernetes API for deployment and configuration (or a Kubernetes MCP server, if you already have one configured — this plugin does not ship one)
Provide all necessary Terraform configurations for EKS cluster setup
Provide all necessary Kubernetes manifests, Karpenter NodePool/EC2NodeClass configurations, and KEDA ScaledObject definitions
Include any required IAM roles, policies, and service account configurations
Please create a complete, production-ready setup with all configuration files needed.

Error Management:

Use kubectl to connect to the Kubernetes API and verify if the EKS cluster exists
If the cluster doesn't exist, ask me if I want to create it and provide the creation steps using Terraform
Check the Kubernetes cluster version and verify compatibility with Karpenter
Recommend the appropriate Karpenter version based on the cluster version
If there's a version incompatibility, suggest either upgrading the cluster or using a compatible Karpenter version
