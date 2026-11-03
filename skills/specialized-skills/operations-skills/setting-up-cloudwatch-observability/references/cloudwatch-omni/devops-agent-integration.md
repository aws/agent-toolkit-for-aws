# Connecting the AWS DevOps Agent to CloudWatch Omni

This reference covers only the **CloudWatch Omni side** of the AWS DevOps Agent:
linking a Space to an existing DevOps Agent space so Omni can hand root-cause
investigations to it. Everything about the AWS DevOps Agent itself (creating and
configuring an agent space, its roles and authentication, running investigations,
following them, and chatting with the agent from a coding agent) belongs to its
dedicated skill: the **`aws-agents-for-devsecops`** plugin in the Agent Toolkit for
AWS (`setup-devops-agent`, `investigating-incidents-with-aws-devops-agent`,
`chatting-with-aws-devops-agent`). Point the customer there for those tasks; do not
reconstruct them here.

AWS DevOps Agent is the native agent CloudWatch Omni uses for root-cause analysis
and incident investigation. Until a Space is linked to a DevOps Agent space,
Investigations reports *"AWS DevOps Agent is not connected. Ask a space
administrator to connect it in integrations and try again."*

## Prerequisites

All three must hold before the connect flow works:

1. **A DevOps Agent space exists in the same AWS account** the customer accesses
   CloudWatch Omni from. If there is none, it is created on the AWS DevOps Agent
   side (its console, or the `aws-agents-for-devsecops` plugin's `setup-devops-agent`
   skill), not in Omni.
2. **Sign-in matches.** If the Omni Domain uses IAM Identity Center, the DevOps
   Agent space must use IAM Identity Center as well.
3. **The operator role can call the DevOps Agent.** `CloudWatchOmniSpaceAccessPolicy`
   grants no `aidevops:*` actions, so a Space admin attaches the
   `AIDevOpsAgentFullAccess` AWS managed policy to the Space's operator role
   (`CloudWatchOmniOperatorRole` by default):

   ```bash
   aws iam attach-role-policy --role-name CloudWatchOmniOperatorRole \
     --policy-arn arn:aws:iam::aws:policy/AIDevOpsAgentFullAccess
   ```

   Use the Space's actual operator role name if it is not `CloudWatchOmniOperatorRole`.

## Connecting

A **Space admin** does this once per Space, in the CloudWatch Omni web app:

1. Go to **Settings → Integrations** and, under **Sub agents → AWS Agents**, open
   the **AWS DevOps Agent** card. Choose **Select space**.
2. Choose the **Region** the agent space is in, select the agent space, and choose
   **Connect**.

This is a console flow. Do not improvise a CLI command, API call, or CloudFormation
resource for creating the connection.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| The card says **"We found 0 AWS DevOps Agent spaces"** and Select space has nothing to pick | No agent space exists in this account for the selected Region. If it exists elsewhere, choose its Region; otherwise create one on the AWS DevOps Agent side, then return to the card. Recreating the Omni Space or changing access grants does not help. |
| Investigations says **"AWS DevOps Agent is not connected"** | The Space has not been linked yet. A Space admin runs the connect flow above; retrying or editing a query, alert, or dashboard does not fix it. |
| The connect or an investigation fails with an authorization error | Check the prerequisites: `AIDevOpsAgentFullAccess` attached to the operator role, and matching sign-in. An error from inside the DevOps Agent space (its own roles, user access, or Identity Center assignment) is a DevOps Agent configuration issue; route it to the `aws-agents-for-devsecops` plugin. |

## After connecting

Running, following, or chatting with DevOps Agent investigations from a coding agent
is the `aws-agents-for-devsecops` plugin's job.
