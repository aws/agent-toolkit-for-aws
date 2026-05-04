# CloudTrail Operational Auditing

Using CloudTrail for operational debugging: who changed what, when. Not for security threat detection.

## Contents
- [Event types](#event-types)
- [Event history](#event-history)
- [Common operational queries](#common-operational-queries)
- [Querying CloudTrail logs](#querying-cloudtrail-logs)
- [CloudTrail → CloudWatch integration](#cloudtrail--cloudwatch-integration)

---

## Event types

| Type | Description | Default logging | Cost |
|------|-------------|:-:|------|
| **Management events** | Control plane (CreateBucket, RunInstances, IAM changes) | Yes | First copy included |
| **Data events** | Data plane (S3 GetObject, Lambda Invoke, DynamoDB GetItem) | No | Additional cost |
| **Network activity events** | VPC endpoint activity | No | Additional cost |
| **Insights events** | Unusual API call rate or error rate | No | Additional cost |

---

## Event history

- **90 days** of management events retained by default, no trail required
- Searchable in console by event name, resource type, user name, time range
- **200,000 event limit** when downloading
- Single account, single Region only
- Cannot view data events, Insights events, or network activity events

### Common lookups
```bash
# Who deleted an S3 bucket?
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=DeleteBucket \
  --start-time 2026-04-20T00:00:00Z

# Who modified a security group?
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=AuthorizeSecurityGroupIngress

# Who stopped an EC2 instance?
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=ResourceName,AttributeValue=i-1234567890abcdef0
```

---

## Common operational queries

### "Who deleted my resource?"
1. Check Event History (90 days) for `Delete*` events
2. Filter by resource name or resource type
3. Look at `userIdentity.arn` for the actor and `sourceIPAddress` for origin

### "Who changed this configuration?"
1. Search for `Update*`, `Modify*`, `Put*` events on the resource
2. Compare `requestParameters` across events to see what changed

### "What happened during the incident?"
1. Filter by time range of the incident
2. Look for `errorCode` fields (AccessDenied, ThrottlingException)
3. Correlate with CloudWatch metrics/logs for the same time window

### "Who accessed my data?" (requires data events)
Data events must be explicitly enabled on the trail:
```bash
aws cloudtrail put-event-selectors --trail-name my-trail \
  --advanced-event-selectors '[{
    "Name": "S3DataEvents",
    "FieldSelectors": [
      {"Field": "eventCategory", "Equals": ["Data"]},
      {"Field": "resources.type", "Equals": ["AWS::S3::Object"]}
    ]
  }]'
```

---

## Querying CloudTrail logs

### Recommended: Trail → S3 → Athena

For new setups, deliver CloudTrail logs to S3 and query with Amazon Athena:

```sql
SELECT eventTime, userIdentity.arn, sourceIPAddress, eventName
FROM cloudtrail_logs
WHERE eventName = 'DeleteBucket'
  AND eventTime > '2026-04-20'
ORDER BY eventTime DESC
LIMIT 100;
```

This is the long-term supported approach — works with standard SQL, scales to any volume, and integrates with existing S3-based analytics.

---

## CloudTrail → CloudWatch integration

### Alert on specific API calls
```
CloudTrail → Trail → CloudWatch Logs → Metric Filter → CloudWatch Alarm → SNS
```

1. Configure trail to deliver events to a CloudWatch Logs log group
2. Create metric filter for the event pattern (e.g., `{ $.eventName = "DeleteBucket" }`)
3. Create alarm on the metric filter
4. Configure SNS notification

### Event selectors
- **Basic**: simple include/exclude for management and data events
- **Advanced**: fine-grained filtering by event source, resource type, resource ARN
- Exclude high-volume management event sources on trails: AWS KMS, RDS Data API
- Max **250 data resources** across all basic event selectors per trail (does not apply to advanced event selectors)
