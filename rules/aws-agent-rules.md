# AWS Guidance

- Where these AWS rules conflict with the project's own instructions, the
  project's instructions take precedence.
- Prefer the AWS MCP Server for AWS interactions — it provides sandboxed
  execution, observability, and audit logging. If unavailable, use the
  AWS CLI directly.
- Before starting a task, check whether a relevant AWS skill is available.
  Load the skill with `retrieve_skill` and prefer its guidance over
  general knowledge.
- When uncertain about specific AWS details (API parameters, permissions,
  limits, error codes), verify against documentation rather than guessing.
  State uncertainty explicitly if you cannot confirm.
- Before reporting a count, a total, or that something does not exist, read
  every page of the results and search every Region and scope where it could
  be. If you could not, say the result is partial and name what you checked.
- To say what a system currently does, read what the runtime uses: the
  completed deployment, the alias or version that is invoked, the template the
  stack is running. A newer stored version, a draft, or a description field is
  not evidence of live behavior.
- Present a cause as confirmed only if data, configuration, or logs you read
  show it. Label anything else as unverified, and say what you would check
  next.
- Before you interpret the records that show a failure, such as error log
  lines, failed executions, or table items, read one of them whole, with
  every field. Don't truncate messages or select fields in your own code
  until you have.
- When an error says a value was undefined, null, empty, or missing, find
  the input, query result, or item that supplied that value. If the account
  shows why it was empty, such as no item matching the key, read that
  before you call the cause unverified.
- When a field in a record you read explains the result, such as an error
  counter, an empty array, a null, or a state value, name the field and its
  exact value in the answer, and say which record it came from.
- When the user asks a specific question or names a suspected cause, confirm
  or rule out each cause they raised, and do not offer alternatives your evidence
  does not support.
- When creating infrastructure, prefer infrastructure-as-code (AWS CDK or
  CloudFormation) over direct CLI commands.
- When working with infrastructure, follow AWS Well-Architected Framework
  principles.
- Do not use em dashes in AWS resource names or descriptions. Use
  hyphens instead.

## Before you conclude

- Before deciding the AWS account can't hold what the request asks for,
  look. List the places it could live, such as S3 buckets, databases, and
  log groups, and read what is there.
- Don't conclude that records are missing from metadata, such as a
  creation date or a stored-bytes count, or from one query that failed or
  came back empty. Read the records another way, across the full time
  range, before reporting them absent.
- A tool's own error is evidence. If a call the answer depends on fails
  with expired or missing credentials or AccessDenied, report that error
  and what it blocks, and don't overrule it with another check. Searching
  other Regions is for finding resources, not for retrying an auth error.
  Retry throttling with backoff before you report it.

## Secret Safety

- MUST load the `aws-secrets-manager` skill first for any secret,
  credential, API key, token, or password task. MUST NOT call
  `secretsmanager get-secret-value` or `batch-get-secret-value`, and MUST
  NOT hit the Secrets Manager Agent daemon directly. MUST use
  `{{resolve:secretsmanager:secret-id:SecretString:json-key}}` with
  `asm-exec` so the secret resolves at runtime without entering context.
