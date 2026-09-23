# Connecting Slack to CloudWatch Omni

This reference covers **first-time setup**: connecting a Slack workspace for your
CloudWatch Omni account and granting the operator role permission to use it. Using
the connection afterwards (posting findings to a channel, being @mentioned to start
an investigation, or searching Slack for context) happens in Slack and the
CloudWatch console and is not covered by these skills. The one exception is Slack
as an **alert notification target**, which is covered in
`aws-observability` → `references/cloudwatch-omni/alerts.md`.

The Slack connection is an account-level integration. Its name is unique within
the AWS account, and its scope is `ACCOUNT` by default, so connecting Slack once
makes it available to every Space in that account rather than to a single Space.
Letting an individual Space use the connection is a separate grant step (see
"Granting CloudWatch Omni permission to use Slack" below).

## Who sets this up

A **Space admin** connects Slack. It is a self-serve action, configured once per
account rather than per Space, and once connected it is available to every Space
in the account. It requires access to the AWS account behind the Space and a
Slack workspace admin who can approve the requested scopes. You can connect
either through the CloudWatch Omni web app or through the CloudWatch Omni API
(see "Connecting Slack through the API" below). In both flows a human must
complete the interactive Slack authorization in a browser; CloudWatch Omni cannot
approve the Slack scopes itself.

## Connecting Slack

1. Open **Settings → Integrations → Slack** in the CloudWatch Omni web app.
2. Choose **Enable** on the Slack card. This opens Slack authorization in a new
   tab.
3. Approve the authorization in your Slack workspace. A workspace admin must
   complete this step.
4. Slack returns to CloudWatch Omni and the integration becomes active. All calls
   to the Slack API use HTTPS, and the Slack bot token is held securely by the
   service, so you do not manage it directly.

## Connecting Slack through the API

The console flow above is backed by CloudWatch Omni API operations, so the
connection can also be driven programmatically (for example, by the assistant on
your behalf) rather than only by clicking through the web app. A human still
completes the Slack authorization in a browser: the API produces the consent link
but cannot approve the requested scopes.

| Action | CLI |
|---|---|
| Start the connection | `aws cloudwatch-omni create-integration --integration-type SLACK --name <name>` |
| Check whether Slack is already connected | `aws cloudwatch-omni list-integrations` |
| Read one integration's state | `aws cloudwatch-omni get-integration --identifier integrationId=<integration-id>` (`identifier` is a union; `integrationArn=<arn>` or `integrationName=<name>` also work) |
| Disconnect | `aws cloudwatch-omni delete-integration --integration-id <integration-id>` |

`CreateIntegration` returns `integration.authorizationUrl` (nested in the returned
`integration` object, not top-level) when Slack needs interactive
consent. Hand that URL to a Slack workspace admin to approve the scopes; the
integration stays `PENDING_OAUTH` until they do, then moves to `ACTIVE`, which
`ListIntegrations` and `GetIntegration` report. Creating the integration does not
by itself let a Space use it; grant the Space permission as described below.

## Scopes the connection requests

The connection requests these Slack scopes:

- `chat:write`: post messages to a channel.
- `channels:read` and `groups:read`: list and look up public and private
  channels.
- `app_mentions:read`: receive mentions.
- `im:read` and `im:history`: support direct-message interactions.
- `links:read`: read links shared in messages for context.

Searching Slack messages needs the `search:read` scope, which the connection does
NOT request by default. If you want CloudWatch Omni to search Slack history,
confirm the installed Slack app grants `search:read`; without it, search returns
a missing-scope error.

## Granting CloudWatch Omni permission to use Slack

Connecting Slack creates the integration, but CloudWatch Omni cannot use it until
the integration is granted on the Space. Connecting and granting are two separate
steps.

- On the connected **Slack** card, choose **Grant agent access profile permission
  to reply to Slack messages** (the permission link on the connected Slack card).
  This authorizes CloudWatch Omni to use the Slack integration through a
  `cloudwatch:InvokeIntegration` grant scoped to that integration.
- The Slack integration runs under an **Access Profile**, and that profile's
  `cloudwatch:InvokeIntegration` grant carries a **channel condition** (the
  `channelNames` on the grant, enforced as a Cedar `channelName` context check)
  that decides which channels CloudWatch Omni may post to. Include only channels
  whose members are authorized to see operational findings (see Security
  considerations). A channel that is not in the grant's channel condition is
  denied at authorization — not by Slack.

A Slack card that shows connected but that CloudWatch Omni cannot use almost
always means the permission grant is missing.

## Security considerations

Findings posted to Slack can include account IDs, resource ARNs, IP addresses,
error detail, and potentially PII. Treat any channel CloudWatch Omni posts to as
a place that data will appear.

> **Authorize the recipients first.** Before granting post access to a channel,
> confirm that everyone in it is authorized to see operational findings for the
> Space. Prefer a private channel with restricted membership.

- Summarize or redact findings before posting to a shared channel when they may
  contain sensitive resource or account detail.
- Enable CloudTrail logging for `cloudwatch:InvokeIntegration` and the related
  integration API calls, and encrypt the trail and any log group it delivers to
  with a customer-managed KMS key.
- Review the granted scopes and channel access periodically. If the Slack
  workspace is compromised, disconnect the integration to drop the stored token,
  then reconnect.

## Disconnect

Choose **Disable** on the Slack card to disconnect the integration at any time,
or call `DeleteIntegration` (see "Connecting Slack through the API"). After you
disconnect, CloudWatch Omni can no longer post to or read from Slack for the
account, and the stored token is dropped.

## Troubleshooting

**"Slack is not configured for this Space"**: no active Slack integration exists
for the Space's account, or it has not been granted. Connect Slack from
**Settings → Integrations**, then choose **Grant agent access profile permission
to reply to Slack messages** on the Slack card.

**A post fails with `not_in_channel`**: the bot is not a member of the target
channel. Invite it to the channel (`/invite @Amazon CloudWatch`). This is the
most common cause and the cheapest to check.

**A post to a channel is denied**: the channel is not in the Access Profile
grant's channel condition. Add the channel to the `channelNames` on the Slack
integration's `cloudwatch:InvokeIntegration` grant.

**Slack message search returns a missing-scope error**: the installed Slack app
does not grant `search:read`, which is not requested by default.

## Next: using the connection

Once Slack is connected and granted, CloudWatch Omni can post findings to a
channel and be @mentioned to start an investigation. Day-to-day use (posting a
summary, starting an investigation from an @mention with thread and session memory,
searching Slack for context) happens in Slack and the CloudWatch console; these
skills do not drive it. To have an Omni **alert** notify a Slack channel, see
`aws-observability` → `references/cloudwatch-omni/alerts.md`.
