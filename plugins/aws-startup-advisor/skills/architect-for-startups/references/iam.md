# IAM — Startup Decision Guide

## Stage-Based Recommendation

### Pre-PMF (Seed / <$1M ARR, 1-5 engineers)

- **AWS managed policies are fine.** Don't spend days crafting least-privilege policies when your team is 3 people and you're iterating daily. Use `PowerUserAccess` (no IAM admin) for developers.
- **Skip Identity Center until you have 5+ engineers.** Below that, IAM users with MFA and forced credential rotation is pragmatic. The setup cost of Identity Center + IdP isn't worth it for 2-3 people.
- **One AWS account is fine.** Multi-account is best practice but overkill when you're pre-revenue. Add a second account (prod) when you have paying customers.

### Post-PMF / Growth ($1M-$10M ARR, 5-30 engineers)

- **Set up Identity Center now.** You've delayed long enough. Connect to Google Workspace or Okta (whichever your company already uses).
- **Separate prod account.** If you haven't done this yet, do it before your next compliance audit.
- **Use Access Analyzer.** Generate policies from CloudTrail activity to replace overly broad managed policies. Takes 30 minutes, saves you in your SOC2 audit.
- **Permission boundaries for senior devs** who need to create IAM roles (for Lambda, ECS). Prevents accidental privilege escalation.

### Scale ($10M+ ARR, 30+ engineers)

- Full AWS Organizations with SCPs.
- Account-per-team or account-per-service pattern.
- This is when you hire a security engineer.

## Cost Traps

IAM itself is free, but IAM mistakes cause cost explosions:

| Trap                                       | Impact                                               | Fix                                                    |
| ------------------------------------------ | ---------------------------------------------------- | ------------------------------------------------------ |
| Over-broad Lambda execution role           | Lambda accesses (and pays for) services it shouldn't | Scope to specific DynamoDB tables, S3 buckets by ARN   |
| No region restriction                      | Resources accidentally created in expensive regions  | SCP denying all regions except your primary            |
| No `sts:ExternalId` on cross-account roles | Confused deputy → unauthorized access                | Always require ExternalId for third-party integrations |

## Counterintuitive Advice

- **`AdministratorAccess` for the founding engineer is OK at seed stage.** The blast radius is one account with no customers. Velocity matters more than least privilege when you're proving the idea works. Add guardrails when you add the 4th engineer.
- **Don't implement SCPs until you have 3+ accounts.** SCPs on a single-account org do nothing useful but add debugging complexity.
- **Managed policies > custom policies until SOC2.** Your custom policies will have bugs. AWS managed policies are tested and maintained. Switch to custom when compliance requires it or when you need to restrict specific resources.
- **Skip IAM Access Analyzer findings in dev accounts.** Cross-account access in your dev account is not a security incident. Focus Access Analyzer on prod only.

## Minimum Viable Security Posture by Stage

### Seed (just don't get hacked)

- [ ] MFA on root account (hardware key in a safe)
- [ ] MFA on all IAM users
- [ ] No root access keys ever
- [ ] `PowerUserAccess` for engineers (can't modify IAM)
- [ ] One admin user for IAM changes
- [ ] Enable CloudTrail (default trail is free)

### Series A (preparing for SOC2)

- [ ] Identity Center with Google/Okta SSO
- [ ] Separate prod account
- [ ] Permission boundaries on developer roles
- [ ] Access Analyzer enabled in prod
- [ ] SCP: deny all regions except primary + us-east-1 (for global services)
- [ ] SCP: deny root access key creation

### Series B+ (passing SOC2/HIPAA audits)

- [ ] Full Organizations with OU structure
- [ ] SCPs on every OU
- [ ] Custom least-privilege policies from Access Analyzer
- [ ] Automated credential rotation
- [ ] GuardDuty in all accounts
- [ ] Security Hub aggregating findings

## When to Graduate

| Trigger                      | Action                                                       |
| ---------------------------- | ------------------------------------------------------------ |
| 4th engineer joins           | Move from IAM users to Identity Center                       |
| First paying customer        | Create prod account, move workloads                          |
| SOC2 audit scheduled         | Access Analyzer, SCPs, permission boundaries                 |
| 3rd AWS account              | AWS Organizations + OU structure                             |
| External vendor needs access | Cross-account role with ExternalId (never share credentials) |
