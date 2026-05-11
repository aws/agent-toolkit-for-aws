# Setup CloudWatch Alarm Notifications

## Overview
This SOP guides you through setting up notification channels for CloudWatch alarms using Amazon SNS (Simple Notification Service). It will create SNS topics, configure subscriptions for various notification methods (email, SMS, webhooks), and link them to existing or new CloudWatch alarms.

## Parameters

**alarm_name** (required): The name of the CloudWatch alarm to configure notifications for
**notification_type** (required): Type of notification (email, sms, webhook, lambda, sqs)
**notification_endpoint** (required): The endpoint for notifications (email address, phone number, webhook URL, etc.)
**sns_topic_name** (optional): Custom name for the SNS topic (default: generated from alarm name)
**aws_region** (optional, default: "us-east-1"): AWS region where resources will be created

## Steps

### 1. Verify Dependencies
Check for required tools and warn the user if any are missing.

**Constraints:**

- You MUST verify the following tools are available in your context: call_aws
- You MUST ONLY check for tool existence and MUST NOT attempt to run the tools because running tools during verification could cause unintended side effects, consume resources unnecessarily, or trigger actions before the user is ready
- You MUST inform the user about any missing tools with a clear message
- You MUST ask if the user wants to proceed anyway despite missing tools
- You MUST respect the user's decision to proceed or abort

### 2. Validate Existing CloudWatch Alarm
Verify that the specified CloudWatch alarm exists and gather its current configuration.

**Constraints:**

- You MUST inform the customer that you are checking if the specified alarm exists
- You MUST use call_aws to execute: `aws cloudwatch describe-alarms --alarm-names {alarm_name} --region {aws_region}`
- You MUST verify the alarm exists before proceeding with notification setup
- If the alarm does not exist, You MUST ask the customer if they want to create a new alarm or specify a different existing alarm name
- You MUST display the current alarm configuration to the customer for confirmation

### 3. Create SNS Topic
Create an SNS topic that will be used to send notifications when the alarm is triggered.

**Constraints:**

- You MUST inform the customer that you are creating an SNS topic for alarm notifications
- You MUST use call_aws to execute: `aws sns create-topic --name {sns_topic_name} --region {aws_region}`
- You MUST capture the TopicArn from the response for use in subsequent steps
- You MUST handle cases where the topic already exists gracefully
- You SHOULD use a descriptive topic name that includes the alarm name if no custom name is provided

### 4. Enable SNS Topic Encryption
Configure encryption at rest for the SNS topic to protect sensitive notification data.

**Constraints:**

- You MUST inform the customer that you are enabling encryption for the SNS topic
- You MUST use call_aws to execute: `aws sns set-topic-attributes --topic-arn {topic_arn} --attribute-name KmsMasterKeyId --attribute-value alias/aws/sns --region {aws_region}`
- You MUST use the AWS managed key (alias/aws/sns) for encryption unless the customer specifies a custom KMS key
- You SHOULD inform the customer about the benefits of encryption at rest for compliance and security
- You MUST verify that encryption was successfully enabled by describing the topic attributes

### 5. Configure SNS Topic Policy
Set up appropriate permissions for the SNS topic to allow CloudWatch to publish messages.

**Constraints:**

- You MUST inform the customer that you are configuring topic permissions for CloudWatch access
- You MUST create a policy document that allows CloudWatch service to publish to the SNS topic
- You MUST use call_aws to execute: `aws sns set-topic-attributes --topic-arn {topic_arn} --attribute-name Policy --attribute-value {policy_json} --region {aws_region}`
- You MUST ensure the policy includes the CloudWatch service principal and publish action
- You MUST NOT prompt to set, retrieve or use passwords as the SOP uses IAM roles and policies for authentication

### 6. Create SNS Subscription
Create a subscription to the SNS topic based on the specified notification type and endpoint.

**Constraints:**

- You MUST inform the customer that you are creating a subscription for the specified notification type
- You MUST use call_aws to execute: `aws sns subscribe --topic-arn {topic_arn} --protocol {protocol} --notification-endpoint {notification_endpoint} --region {aws_region}`
- You MUST map notification types to appropriate SNS protocols (email->email, sms->sms, webhook->https, etc.)
- You MUST capture the SubscriptionArn from the response
- For email subscriptions, You MUST inform the customer that they will need to confirm the subscription via email
- For SMS subscriptions, You MUST validate that the phone number is in the correct format (+1234567890)

### 7. Update CloudWatch Alarm with SNS Action
Configure the CloudWatch alarm to send notifications to the SNS topic when triggered.

**Constraints:**

- You MUST inform the customer that you are linking the alarm to the notification topic
- You MUST use call_aws to execute: `aws cloudwatch put-metric-alarm` with the existing alarm configuration plus the new AlarmActions
- You MUST preserve all existing alarm settings while adding the SNS topic ARN to AlarmActions
- You MUST also add the SNS topic ARN to OKActions if the customer wants notifications when alarm returns to OK state
- You MUST verify the alarm update was successful by describing the alarm again

### 8. Test Notification Setup
Verify that the notification system is working by testing the alarm state change.

**Constraints:**

- You MUST inform the customer that you are testing the notification setup
- You MUST use call_aws to execute: `aws cloudwatch set-alarm-state --alarm-name {alarm_name} --state-value ALARM --state-reason "Testing notification setup" --region {aws_region}`
- You MUST wait a few seconds then reset the alarm state back to OK
- You MUST use call_aws to execute: `aws cloudwatch set-alarm-state --alarm-name {alarm_name} --state-value OK --state-reason "Test complete" --region {aws_region}`
- You MUST inform the customer to check their notification endpoint for test messages
- You SHOULD provide guidance on what to do if notifications are not received

### 9. Provide Integration Examples
At the end of the setup, provide examples of testing and integrating the notification system.

**Constraints:**

- You MUST provide AWS CLI examples for testing the alarm and notification system
- You MUST include code snippets in Python, Java, and JavaScript showing how to programmatically trigger alarms or send test notifications
- You MUST provide instructions on how to verify the notification system is working properly
- You MUST explain how to modify or add additional notification endpoints

## Examples

### Example AWS CLI Commands

```bash
# List all alarms
aws cloudwatch describe-alarms --region us-east-1

# Create SNS topic
aws sns create-topic --name MyAlarmNotifications --region us-east-1

# Subscribe email to topic
aws sns subscribe --topic-arn arn:aws:sns:us-east-1:123456789012:MyAlarmNotifications --protocol email --notification-endpoint user@example.com --region us-east-1

# Test alarm state
aws cloudwatch set-alarm-state --alarm-name MyAlarm --state-value ALARM --state-reason "Manual test" --region us-east-1

# List SNS subscriptions
aws sns list-subscriptions-by-topic --topic-arn arn:aws:sns:us-east-1:123456789012:MyAlarmNotifications --region us-east-1
```

### Python Integration Example

```python
import boto3

def create_alarm_with_notifications(alarm_name, metric_name, threshold, sns_topic_arn):
    cloudwatch = boto3.client('cloudwatch')

    cloudwatch.put_metric_alarm(
        AlarmName=alarm_name,
        ComparisonOperator='GreaterThanThreshold',
        EvaluationPeriods=1,
        MetricName=metric_name,
        Namespace='AWS/EC2',
        Period=300,
        Statistic='Average',
        Threshold=threshold,
        ActionsEnabled=True,
        AlarmActions=[sns_topic_arn],
        AlarmDescription='Alarm with SNS notification',
        Unit='Percent'
    )
```

### JavaScript Integration Example

```javascript
const AWS = require('aws-sdk');
const cloudwatch = new AWS.CloudWatch({region: 'us-east-1'});

async function triggerTestNotification(alarmName) {
    const params = {
        AlarmName: alarmName,
        StateValue: 'ALARM',
        StateReason: 'Testing notification from JavaScript'
    };

    try {
        await cloudwatch.setAlarmState(params).promise();
        console.log('Test notification triggered');
    } catch (error) {
        console.error('Error triggering notification:', error);
    }
}
```

### Java Integration Example

```java
import software.amazon.awssdk.services.cloudwatch.CloudWatchClient;
import software.amazon.awssdk.services.cloudwatch.model.SetAlarmStateRequest;

public class AlarmNotificationTest {
    public static void testNotification(String alarmName) {
        CloudWatchClient cloudWatch = CloudWatchClient.create();

        SetAlarmStateRequest request = SetAlarmStateRequest.builder()
            .alarmName(alarmName)
            .stateValue("ALARM")
            .stateReason("Testing notification from Java")
            .build();

        cloudWatch.setAlarmState(request);
    }
}
```

## Troubleshooting

**Email notifications not received**
If email notifications are not working, check that the email subscription was confirmed. Use `aws sns list-subscriptions-by-topic` to verify the subscription status is "Confirmed" rather than "PendingConfirmation".

**SMS notifications failing**
Ensure the phone number is in E.164 format (e.g., +12345678901) and that SMS is supported in your AWS region. Some regions have restrictions on SMS delivery.

**Alarm not triggering notifications**
Verify that the alarm has the correct SNS topic ARN in its AlarmActions. Use `aws cloudwatch describe-alarms` to check the alarm configuration and ensure ActionsEnabled is set to true.
