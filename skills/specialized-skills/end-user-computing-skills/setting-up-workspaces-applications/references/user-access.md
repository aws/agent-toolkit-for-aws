# User Access — how agents and people reach the environment

How sessions get authorized on the environment this skill provisions. Agent and human paths differ; both simple methods are covered here. SAML 2.0 federation and Active Directory domain join are out of this guided flow — route to [Setting Up SAML](https://docs.aws.amazon.com/appstream2/latest/developerguide/external-identity-providers-setting-up-saml.html) and the [Active Directory tutorial](https://docs.aws.amazon.com/appstream2/latest/developerguide/active-directory-directory-setup.html).

## Agents: UserId strategy

Agents connect through the Agent Access MCP server, either by naming the stack and a UserId (the server creates the streaming session) or with a streaming URL from `CreateStreamingURL`. The connection mechanics are the `amazon-workspaces-agent-access` skill. What *this* flow must plan is the `UserId` — and plan it by defaulting, not asking: generate stable UserIds from the environment name (one per concurrent agent, e.g. `invoice-reconciliation-agent-01..NN`), show them in the plan's "defaults chosen for you" with the per-UserId fee noted, and let the user rename them there if they care. The rules the default must respect:

- **One active session per `UserId` per fleet.** N concurrent agents need N distinct UserIds — plan the naming (e.g. `invoice-agent-01..NN`).
- **An observer must reuse the agent's UserId** to view that agent's session (`UserControlMode` VIEW_ONLY/VIEW_STOP) — a different UserId gets a different session.
- **Each unique UserId incurs the monthly per-user RDS SAL fee** on Windows Server fleets (charged in full per month, not pro-rated; unique per auth type + username + region). Reuse stable UserIds month to month rather than generating fresh ones per run — see the [pricing page](https://aws.amazon.com/workspaces/applications/pricing/) for the rate that applies to AI agent use cases.

## Humans: user pool (the simple path)

The user pool is the no-infrastructure human access method — no IdP, no directory. Users sign in through a web portal with email + password:

1. Create each user:

   ```bash
   aws appstream create-user \
     --user-name jane@example.com \
     --authentication-type USERPOOL \
     --first-name Jane --last-name Doe
   ```

2. Associate users with the stack (≤25 per call):

   ```bash
   aws appstream batch-associate-user-stack \
     --user-stack-associations StackName=<stack>,UserName=jane@example.com,AuthenticationType=USERPOOL,SendEmailNotification=true
   ```

3. Each user receives a welcome email with the portal link and a temporary password, signs in, and streams.

Facts that prevent surprises (from the API reference):

- **Email addresses are case-sensitive at login** — a differently-capitalized email gets "user does not exist."
- **The welcome email's temporary password is valid for 7 days** — users who miss the window need a new welcome email (`create-user` with `--message-action RESEND`, without first/last name).
- **User pool users cannot be assigned to stacks whose fleets are domain-joined** — user pools and domain join are mutually exclusive by API rule (one more reason domain join is out of this flow).
- Per-user RDS SAL billing applies to human users on Windows Server fleets exactly as it does to agent UserIds.

## Cleanup

Teardown of a human environment includes `batch-disassociate-user-stack` for the stack's users; delete users (`delete-user`) only if they're not associated with other stacks.
