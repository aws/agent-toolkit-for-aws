# Client Configuration Reference

## botocore.config.Config

All configuration is passed via `botocore.config.Config`. Multiple configs can be merged:

```python
from botocore.config import Config

base = Config(retries={"total_max_attempts": 2, "mode": "standard"})
s3_specific = Config(s3={"addressing_style": "path"})

# Merge -- later config wins on conflicts
client = boto3.client("s3", config=base.merge(s3_specific))
```

## Retry Configuration

```python
config = Config(
    retries={
        "total_max_attempts": 2,    # total attempts including first try (1 retry attempt here)
        "mode": "adaptive",         # legacy | standard | adaptive
    }
)
```

Prefer using `total_max_attempts` over the legacy `max_attempts`.  The
`max_attempts` value does not include the first attempt (it's actually the
number of retry attempts).

| Mode | Default attempts | Behavior |
|---|---|---|
| `legacy` | 5 | Retries on a limited set of errors |
| `standard` | 3 | Broader retryable errors, consistent exponential backoff |
| `adaptive` | 3 | Standard + client-side rate limiting (token bucket) |

Can also set via `AWS_MAX_ATTEMPTS` and `AWS_RETRY_MODE` env vars or `~/.aws/config`.

## Timeouts

```python
config = Config(
    connect_timeout=5,    # seconds to establish connection (default 60)
    read_timeout=10,      # seconds to wait for response data (default 60)
)
```

## Connection Pool

```python
config = Config(
    max_pool_connections=50,  # default 10 per client
)
```

Each client maintains its own urllib3 connection pool. If you're making parallel requests (e.g. with `concurrent.futures`), set `max_pool_connections` to match your concurrency level to avoid connection churn.

## Custom Endpoints

```python
# Custom S3 endpoint on localhost.
client = boto3.client(
    "s3",
    endpoint_url="http://localhost:4566",
    region_name="us-east-1",
)

# FIPS endpoints
config = Config(use_fips_endpoint=True)
client = boto3.client("s3", config=config)

# Dual-stack (IPv4 + IPv6)
config = Config(use_dualstack_endpoint=True)
client = boto3.client("s3", config=config)
```

## Proxy Configuration

```python
# Via environment variables (preferred)
# HTTP_PROXY=http://proxy:8080
# HTTPS_PROXY=http://proxy:8080

# Via Config
config = Config(
    proxies={"https": "http://proxy:8080"},
    proxies_config={"proxy_ca_bundle": "/path/to/ca-bundle.crt"},
)
```

## S3-Specific Configuration

```python
config = Config(
    s3={
        "addressing_style": "path",       # path | virtual | auto (default)
        "payload_signing_enabled": False,  # skip payload signing for large uploads
        "us_east_1_regional_endpoint": "regional",
    },
    signature_version="s3v4",
)

# Transfer acceleration
config = Config(s3={"use_accelerate_endpoint": True})
```

## User-Agent Customization

```python
config = Config(
    user_agent_appid="my-app/1.0",
    user_agent_extra="custom-metadata",
)
```

## Sharing Config Across Clients

```python
from botocore.config import Config

config = Config(
    retries={"total_max_attempts": 2, "mode": "standard"},
    connect_timeout=5,
    read_timeout=10,
)

# Same config for multiple clients
s3 = boto3.client("s3", config=config)
dynamodb = boto3.client("dynamodb", config=config)
lambda_client = boto3.client("lambda", config=config)
```

You can also set a default client config in a botocore Session:

```python
from botocore.config import Config
from botocore.session import Session

config = Config(
    retries={"total_max_attempts": 2, "mode": "standard"},
    connect_timeout=5,
    read_timeout=10,
)
session = Session()
session.set_default_client_config(config)
# Now all clients created will use this session-specific default
# config if an explicit config is not provided.
s3 = session.create_client('s3')
dynamodb = session.create_client('dynamodb')
```
