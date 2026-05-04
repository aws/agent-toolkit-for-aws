# AgentCore Runtime — Container Build Procedure

## Table of Contents

- Overview
- Parameters
- Steps: Verify Protocol, Write Dockerfile, Write Application Entry Point, Build and Push to ECR, Verify Image
- Security Considerations

## Overview

Deterministic procedure for building an ARM64 container image that meets
AgentCore Runtime's container contract and pushing it to ECR. Each protocol
has a different container contract — you MUST select the protocol before
building.

## Parameters

- **protocol** (required): `http` | `mcp` | `a2a` | `ag-ui` — see [runtime reference](agentcore-runtime.md) for selection guide
- **framework** (optional): `fastapi` | `express` | `flask` | `custom`
- **ecr_repo** (required): ECR repository URI

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters (`protocol`, `ecr_repo`) upfront in a single prompt
- You MUST confirm successful acquisition before proceeding to Step 1
- You SHOULD ask about the optional `framework` parameter in the same prompt

## Steps

**General constraints:**

- You MUST present an overview of the steps before starting
- You MUST explain to the user what step is being executed and why before running each command
- You MUST respect the user's decision to abort at any point
- You MUST confirm the protocol choice before building the container (changing protocol requires rebuilding)

### 1. Verify Protocol and Container Contract

**Constraints:**

- You MUST verify Docker is available and supports buildx for ARM64 builds: `docker buildx version`
- You MUST verify the AWS CLI is available for ECR authentication: `aws --version`
- You MUST inform the user about any missing tools and ask if they want to proceed
- You MUST confirm the protocol with the user before writing the Dockerfile
- Each protocol has a different contract:

| Protocol | Health Endpoint | Port | Key Requirement |
|----------|----------------|------|-----------------|
| HTTP | `/health` | 8080 | JSON request/response |
| MCP | `/mcp` | 8080 | Streamable HTTP transport, tool registration |
| A2A | `/.well-known/agent.json` | 8080 | Agent Card discovery, task management |
| AG-UI | `/ping` | 8080 | SSE event stream via `/invocations`, health via `/ping` |

- You MUST NOT mix protocol contracts — an HTTP health check won't work for MCP

### 2. Write Dockerfile

**Constraints:**

- You MUST use ARM64 base image — AgentCore runs on Graviton. x86 images will fail to start.
- You MUST use multi-stage build to minimize image size
- You MUST expose the correct port (default 8080)
- You SHOULD use Python 3.12+ slim or Node.js 20+ slim as base

**Example Dockerfile (HTTP/FastAPI):**

```dockerfile
FROM --platform=linux/arm64 python:3.12.4-slim AS builder
WORKDIR /app
RUN python -m venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

FROM --platform=linux/arm64 python:3.12.4-slim
RUN useradd -r -u 1001 appuser
WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"
USER appuser
EXPOSE 8080
# Binds to 0.0.0.0 for AgentCore internal routing. Do NOT expose directly to the internet.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

### 3. Write Application Entry Point

**Constraints:**

- You MUST implement the health check endpoint for the selected protocol
- You MUST handle SIGTERM for graceful shutdown
- You MUST read AgentCore environment variables (RUNTIME_ID, AWS_REGION)
- You MUST log to stdout/stderr (AgentCore routes to CloudWatch)

**HTTP (FastAPI) example:**

> **Note:** These examples omit authentication because AgentCore handles auth at the platform layer. If running outside AgentCore (e.g., local testing), you MUST add authentication middleware before exposing to any network.

```python
from fastapi import FastAPI
import signal, sys

app = FastAPI()

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.post("/invoke")
async def invoke(request: dict):
    # Agent logic here
    return {"response": "..."}

def shutdown(sig, frame):
    sys.exit(0)

signal.signal(signal.SIGTERM, shutdown)
```

**MCP example:**

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("my-agent")

@mcp.tool()
def my_tool(query: str) -> str:
    """Tool description for discovery."""
    return "result"

# Runs on /mcp with Streamable HTTP transport
mcp.run(transport="streamable-http", host="0.0.0.0", port=8080)
```

> **Note:** This minimal example omits SIGTERM handling for brevity. You MUST add graceful shutdown handling (see the HTTP example above) before deploying to AgentCore.

**A2A example (minimal contract):**

```python
from fastapi import FastAPI

app = FastAPI()

# Agent Card discovery endpoint — REQUIRED for A2A protocol
@app.get("/.well-known/agent.json")
async def agent_card():
    return {
        "name": "my-agent",
        "description": "Agent description",
        "capabilities": ["task_execution"],
        "endpoint": "http://localhost:8080",  # Replace with AgentCore-assigned URL at deployment
    }

@app.post("/tasks")
async def create_task(request: dict):
    # Task execution logic
    return {"taskId": "...", "status": "completed", "result": "..."}
```

> **Note:** This minimal example omits SIGTERM handling for brevity. You MUST add graceful shutdown handling (see the HTTP example above) before deploying to AgentCore.

**AG-UI example (minimal contract):**

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, JSONResponse
import json

app = FastAPI()

@app.get("/ping")
async def ping():
    return JSONResponse({"status": "Healthy"})

@app.post("/invocations")
async def invocations(request: dict):
    async def event_stream():
        yield f"data: {json.dumps({'type': 'RUN_STARTED', 'threadId': 'thread-1', 'runId': 'run-1'})}\n\n"
        yield f"data: {json.dumps({'type': 'TEXT_MESSAGE_CONTENT', 'messageId': 'msg-1', 'delta': 'response'})}\n\n"
        yield f"data: {json.dumps({'type': 'RUN_FINISHED', 'threadId': 'thread-1', 'runId': 'run-1'})}\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

> **Note:** This minimal example omits SIGTERM handling for brevity. You MUST add graceful shutdown handling (see the HTTP example above) before deploying to AgentCore.

Refer to the latest AWS documentation on AgentCore A2A protocol and AG-UI protocol for current full specifications — these protocols are evolving and the full contract may have changed.

### 4. Build and Push to ECR

**Constraints:**

- You MUST build for ARM64: `docker buildx build --platform linux/arm64 --load -t <tag> .`
- You MUST authenticate to ECR before pushing:

  ```bash
  aws ecr get-login-password --region <region> | docker login --username AWS --password-stdin <account>.dkr.ecr.<region>.amazonaws.com
  ```

- You MUST tag with both `latest` and a version tag for rollback:

  ```bash
  docker tag <image> <ecr_repo>:latest
  docker tag <image> <ecr_repo>:v1.0.0
  docker push <ecr_repo>:latest
  docker push <ecr_repo>:v1.0.0
  ```

### 5. Verify Image

**Constraints:**

- You MUST verify the image architecture is ARM64:

  ```bash
  docker inspect <image> | grep Architecture
  ```

- You SHOULD test locally before deploying to AgentCore:

  ```bash
  docker run --platform linux/arm64 -p 8080:8080 <image>
  # Use the health endpoint for your protocol:
  # HTTP: /health | MCP: /mcp | A2A: /.well-known/agent.json | AG-UI: /ping
  curl http://localhost:8080/<health-endpoint>
  ```

- If health check fails locally, it will fail on AgentCore — fix before deploying

## Security Considerations

**Authentication and network exposure:**

- AgentCore authenticates requests at the platform layer before they reach your container — the code examples omit auth because AgentCore handles it
- You MUST NOT expose this container directly to the internet without adding your own authentication layer
- For local testing, bind to `127.0.0.1` instead of `0.0.0.0` to prevent network exposure: `uvicorn main:app --host 127.0.0.1 --port 8080`
- The Dockerfile uses `--host 0.0.0.0` because AgentCore routes traffic to the container internally — do NOT expose port 8080 directly

**Transport security:**

- AgentCore terminates TLS at the load balancer — your container receives plaintext HTTP on port 8080 over the internal network
- You MUST NOT expose port 8080 directly to the internet — all external traffic must route through AgentCore
- If deploying outside AgentCore, you MUST configure TLS (use ACM for certificate management)

**Input validation:**

- You MUST validate and sanitize all input before processing — use Pydantic models or equivalent schema validation
- You MUST set maximum request body size limits to prevent denial-of-service
- You MUST handle malformed input gracefully with appropriate error responses
- You SHOULD include security headers in HTTP responses: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Cache-Control: no-store`

**Container image security:**

- You MUST NOT bake secrets, API keys, or credentials into the Docker image — use Secrets Manager at runtime for secrets; use environment variables only for non-sensitive configuration (RUNTIME_ID, AWS_REGION)
- You MUST run the container as a non-root user (the example Dockerfile uses `USER appuser` — do not remove this)
- You MUST use multi-stage builds to exclude build-time dependencies (compilers, pip cache, dev packages) from the final image
- You SHOULD pin base image versions (e.g., `python:3.12.4-slim` not `python:3.12-slim`) to avoid supply chain attacks from tag mutation
- You SHOULD enable ECR image scanning: `aws ecr put-image-scanning-configuration --repository-name <repo> --image-scanning-configuration scanOnPush=true`

**ECR access control:**

- Scope ECR push permissions to the specific repository ARN — avoid `ecr:*` on `Resource: "*"`
- The ECR login token from `get-login-password` is ephemeral (12 hours) — do not store or share it
- You MUST NOT log the ECR login token in agent output

**Runtime security:**

- AgentCore injects credentials via environment variables (AWS_ACCESS_KEY_ID, etc.) — do not override these
- Log to stdout/stderr only — AgentCore routes to CloudWatch with encryption
- You MUST NOT log request or response bodies that may contain PII or sensitive model inputs/outputs
- Handle SIGTERM for graceful shutdown to avoid data loss during scaling events
- Enable CloudTrail logging for ECR API calls to audit image push/pull activity
- Refer to the latest AWS documentation on ECR security best practices and Bedrock security best practices
