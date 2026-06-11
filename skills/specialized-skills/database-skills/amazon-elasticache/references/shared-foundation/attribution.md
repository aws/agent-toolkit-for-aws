# Attribution

How to identify and track resources created or managed by the ElastiCache skill. This file is loaded on demand when generating CLI commands, SDK code, or IaC templates (see SKILL.md "Reference loading").

## Core Rule

Every AWS API call the skill generates -- whether via CLI, SDK, or script -- must include the `AWSSkill-ElastiCache` user-agent identifier. Every resource the skill creates must carry the attribution tags defined below. These two mechanisms work together: user-agent covers ephemeral actions (describe, modify), tags cover persistent resources.

## App ID / User-Agent

The `AWS_SDK_UA_APP_ID` environment variable makes all SDK and CLI calls include the skill identifier in the user-agent string.

**Environment variable:**

```
AWS_SDK_UA_APP_ID=AWSSkill-ElastiCache
```

### How It Works

- The AWS SDK (all languages) reads `AWS_SDK_UA_APP_ID` and appends it to the `User-Agent` HTTP header on every API call.
- CloudTrail records the `userAgent` field in every event log entry.
- CloudTrail Lake can query events by user-agent to find all actions taken by the skill.

### Where It Is Set (Primary Path)

- **AWS CLI / SDK**: The identifier is set via the AWS CLI and SDK as the primary path, through the `AWS_SDK_UA_APP_ID` environment variable or the SDK user-agent config. See "Where the Agent Must Set It" below.

### Where the Agent Must Set It

- **CLI commands**: Prefix any `aws elasticache` command block with `export AWS_SDK_UA_APP_ID=AWSSkill-ElastiCache`.

- **SDK code (control-plane)**: Set the app ID on the client. The config key varies by SDK:
  - Python (boto3): `botocore.config.Config(user_agent_appid="AWSSkill-ElastiCache")`
  - Node.js (SDK v3): Set `AWS_SDK_UA_APP_ID=AWSSkill-ElastiCache` environment variable (preferred), or programmatically via `new ElastiCacheClient({ appId: "AWSSkill-ElastiCache" })`
  - Java (SDK v2): `.overrideConfiguration(ClientOverrideConfiguration.builder().appId("AWSSkill-ElastiCache").build())` or JVM system property `-Dsdk.ua.appId=AWSSkill-ElastiCache` (Note: the Kotlin SDK uses `-Daws.userAgentAppId` instead). Note: Java SDK v2 does not support the `AWS_SDK_UA_APP_ID` environment variable.
  - Go (SDK v2): `config.WithAppID("AWSSkill-ElastiCache")`

- **Scripts**: Bundled scripts that use boto3 should include the `user_agent_appid` config when constructing clients.

### Where It Does NOT Apply

- **CloudFormation / CDK deploys**: CloudFormation does not support custom user-agent strings. Use resource tags for attribution instead (see below).
- **Data-plane client connections** (redis-py, ioredis, Lettuce, go-redis connecting to the cache): These are not AWS API calls. Do not add `AWS_SDK_UA_APP_ID` to data-plane client code.

## Resource Tags

Tag schema (`managed_by`, `skill`, `skill_version`, `created_by`, `generation_model`) and examples are in `setup/create-secure-cache.md`. This section covers only the gotchas.

### Enterprise Tag Policy Compatibility

If the target AWS account uses AWS Organizations tag policies that restrict allowed tag keys, the skill's default tags (`managed_by`, `skill`, `skill_version`, `created_by`, `generation_model`) may be rejected. If tag application fails due to an Organization tag policy, remove the conflicting tags and proceed. Attribution tags are best-effort, not a gate -- cache creation should never fail because of attribution.

## What NOT to Use

- **Do not** use key prefixes in cached data for attribution. This pollutes the data namespace and adds overhead to every operation.
- **Do not** use synthetic commands or hidden keys to mark the cache as skill-managed. This creates operational confusion.
- **Do not** use outbound beacons or telemetry calls. The skill does not phone home.
