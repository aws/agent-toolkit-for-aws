# Permissions

Grant the caller only the policy for the steps they run. This skill never changes IAM. Replace the Region, account, and job names.

## Assess and review (read-only)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadJobsAndEvaluations",
      "Effect": "Allow",
      "Action": ["glue:GetJobs", "glue:GetJob", "glue:GetJobRun", "glue:GetJobUpgradeAnalysis"],
      "Resource": "*"
    },
    {
      "Sid": "ReadScriptsForAssessment",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::amzn-s3-demo-bucket/scripts/*"
    }
  ]
}
```

The `spark-upgrade` MCP server also needs the caller's access to that service. If a summary location is an `s3://` URI, add `s3:GetObject` on it. If the summaries use your AWS KMS key, add `kms:Decrypt` on that key.

## Turn on, turn off, and decide

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "UpdateJobsAndRecordDecisions",
      "Effect": "Allow",
      "Action": ["glue:GetJob", "glue:GetJobUpgradeAnalysis", "glue:UpdateJob", "glue:CreateJob", "glue:StartJobUpgradeAnalysis"],
      "Resource": "arn:aws:glue:us-west-2:111122223333:job/*"
    },
    {
      "Sid": "PassTheJobRole",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::111122223333:role/MyGlueJobRole",
      "Condition": {"StringEquals": {"iam:PassedToService": "glue.amazonaws.com"}}
    }
  ]
}
```

## Email notifications

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ManageTheNotificationTopic",
      "Effect": "Allow",
      "Action": ["sns:CreateTopic", "sns:GetTopicAttributes", "sns:SetTopicAttributes",
                 "sns:Subscribe", "sns:ListSubscriptionsByTopic"],
      "Resource": "arn:aws:sns:us-west-2:111122223333:glue-auto-upgrade-notifications"
    },
    {
      "Sid": "ListTopics",
      "Effect": "Allow",
      "Action": "sns:ListTopics",
      "Resource": "*"
    },
    {
      "Sid": "ManageTheNotificationRules",
      "Effect": "Allow",
      "Action": ["events:DescribeRule", "events:PutRule", "events:PutTargets", "events:ListTargetsByRule"],
      "Resource": "arn:aws:events:us-west-2:111122223333:rule/glue-auto-upgrade-*"
    }
  ]
}
```
