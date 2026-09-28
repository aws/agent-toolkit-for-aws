---
source_url: https://aws.amazon.com/startups/prompt-library/rag-chatbot-with-claude
title: "RAG Chatbot with Claude"
tags: ["Prototyping", "Deployment", "Beginner", "Lambda", "S3"]
---

## RAG Chatbot with Claude

Create a serverless, React-based chatbot using Claude on Bedrock with RAG capabilities for PDF documents.

## System Prompt

## AWS Claude RAG Chatbot Architecture Design Request

## Project Overview

I need a comprehensive design for a web-based chatbot application with the following key components:

- Claude 3 Sonnet on Amazon Bedrock as the LLM
- RAG capabilities for PDF documents stored in S3
- React frontend with real-time chat functionality

## Detailed Requirements

### 1. Core Functionality

- **User Interface**: Web-based chat interface built with React
- **AI Backend**: Claude 3 Sonnet model via Amazon Bedrock API
- **RAG System**:
  - PDF document search and retrieval from S3
  - Document upload functionality for expanding knowledge base
  - Vector search across 1000+ documents
- **Persistence**:
  - Chat history storage and retrieval
  - User authentication and session management

### 2. Performance Requirements

- Support for 100 concurrent users
- Response times under 2 seconds for typical queries
- Ability to process and index documents up to 100MB each

### 3. Cost Optimization Targets

- Monthly operational cost under $200 for moderate usage
- Strategic use of spot instances where appropriate
- Caching implementation to minimize Bedrock API calls
- Pay-per-use services prioritized

### 4. Technical Architecture Preferences

- Serverless backend architecture (AWS Lambda)
- Vector database for embeddings (OpenSearch or equivalent)
- PDF processing pipeline for text extraction and embedding
- WebSocket implementation for real-time chat experience
- API Gateway for REST endpoint management

### 5. Security & Compliance Requirements

- End-to-end encryption for documents (at rest and in transit)
- IAM roles configured with least privilege principle
- Rate limiting implementation to prevent system abuse
- Comprehensive audit logging for all system interactions

## Deliverables Requested

1. Complete AWS solution architecture diagram
2. Infrastructure as Code (Terraform preferred)
3. Detailed deployment guide with step-by-step instructions
4. Cost estimation breakdown by AWS service
5. Security implementation details
6. Readme with full documentation

Please provide a solution that adheres to AWS Well-Architected Framework principles, with particular attention to reliability, performance efficiency, and cost optimization.
Provide your complete solution architecture without any preamble, starting with the high-level architecture diagram description.
