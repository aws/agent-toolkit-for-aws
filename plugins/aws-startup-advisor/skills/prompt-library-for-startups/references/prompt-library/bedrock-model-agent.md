---
source_url: "https://startups.aws.com/prompt-library/bedrock-model-agent"
title: "Bedrock Model Availability Agent"
kind: "agent"
install_source: "https://github.com/aws-samples/sample-genai-startups/tree/main/agentic-coding-library/agents/bedrock-model-agent"
tags: []
---

## Bedrock Model Availability Agent

A Kiro CLI custom agent that finds Amazon Bedrock model availability across AWS regions using a custom MCP server.

## About this agent

<!-- markdownlint-disable -->

# Bedrock Model Agent

The Bedrock Model Agent is a tool designed to help users find Amazon Bedrock model availability across regions. It acts as a Bedrock Model Availability Assistant, providing information on foundation model availability across AWS regions.

## Use Cases

- Checking Model Availability: Users can query the agent to find out which Bedrock models are available in specific AWS regions.
- Cross-Region Model Access: Helps users determine if a model is available in multiple regions, aiding in deployment decisions.
- Model Selection: Assists in selecting the appropriate model based on regional availability and other criteria.

## MCP Servers

The configuration includes the following MCP server:

- bedrock-model: This server is responsible for managing the Bedrock model availability. It runs the command `uv` with arguments to execute the `bedrock-model-mcp` script located in the `.bedrock-model-mcp` directory.

## Target Personas

This agent is beneficial for:

- AWS Developers: Developers working with Amazon Bedrock who need to check model availability across regions.
- DevOps Engineers: Professionals responsible for deploying and managing AI models on AWS who require information on model availability.
- Data Scientists: Individuals who use Bedrock models and need to know which models are available in their target regions.
- IT Administrators: Administrators managing AWS resources who need to ensure model availability for their applications.

<!-- markdownlint-enable -->

## Install

Install source: <https://github.com/aws-samples/sample-genai-startups/tree/main/agentic-coding-library/agents/bedrock-model-agent>

This agent installs separately from this skill, into the user's AI coding agent.
