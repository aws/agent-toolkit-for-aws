# Checking credits and coverage

Everything here is **observed against a live AWS account**, not inferred from documentation. Where an
observed value differs from the API reference, the observed value is what your code has to handle — those
cases are marked below.

## The command

```bash
aws billing get-credits --account-id <ACCOUNT_ID> --start-date <EPOCH_ONE_YEAR_AGO> --region us-east-1
```

Compute `<EPOCH_ONE_YEAR_AGO>` yourself — Unix seconds for one year before today. Do not shell out to `date`: `date -v-1y` is BSD, `date -d '1 year ago'` is GNU, and neither exists on Windows, where this plugin also runs.

Get the account id from `aws sts get-caller-identity --query Account --output text`.

Requires **AWS CLI 2.35.23 or newer**. Older CLIs do not have the `billing` command group at all — check
with `aws --version` first and say so rather than letting the command fail confusingly. On macOS with
Homebrew: `brew upgrade awscli`.

## No AWS credentials at all

Check before you reach for credits:

```bash
aws sts get-caller-identity
```

If that fails with `Unable to locate credentials`, the user has no AWS credentials in this environment.
That is **not an error to report and stop on** — it is a normal state, especially for someone evaluating
before committing to anything.

Everything up to this point still works. You can assess whether DevOps Agent fits, explain what it does,
and give list pricing. What you cannot do is show *their* numbers or connect anything.

Say it as a fact, not a failure:

> "I can't see your AWS account from here, so I can't tell you what your own credits cover. Here's what it
> costs in general, and what I'd want to check once you're connected."

Then continue with the qualitative path in `affordability.md`. Do not push them to authenticate in order to
keep reading — a founder deciding whether this is worth it should be able to decide before signing into
anything.

## Failure mode you will hit most often

```
AccessDeniedException: IAM user access not activated
```

**This is not a permissions problem and no IAM policy fixes it.** IAM users and roles cannot read Billing
data by default — including principals holding `AdministratorAccess`. It is a separate account-level
setting that **only the root user can turn on**:

> AWS Console → Account → *IAM User and Role Access to Billing Information* → Edit → activate

When you hit this, tell the user exactly that. Do not report it as "no credits found," do not report it as
a permissions error they can fix with a policy, and do not silently skip the credit disclosure. Say:

> I can't read your credit balance — your AWS account's root user needs to turn on IAM access to billing
> information first. No IAM permission grants this. Here's what it costs regardless: …

Then continue with the cost disclosure using list pricing. **Unknown is not zero and unknown is not
covered.**

## Reading the response

```json
{
  "credits": [
    {
      "creditType": "Promotion",
      "description": "AWS Free Tier",
      "creditStatus": "ENABLED",
      "initialAmount":   { "currencyCode": "USD", "currencyAmount": "100.000000" },
      "remainingAmount": { "currencyCode": "USD", "currencyAmount": "0.000000" },
      "endDate": "2026-08-12T17:34:27-07:00",
      "exhaustDate": "2026-01-01T14:16:01-08:00",
      "applicationType": "AfterDiscounts",
      "applicableProductNames": ["Amazon EC2", "AWSDevOpsAgent", "..."]
    }
  ]
}
```

### Does this credit cover AWS DevOps Agent?

Check `applicableProductNames` for the literal string:

```
AWSDevOpsAgent
```

**PascalCase, no spaces.** Matching the display name `"AWS DevOps Agent"` finds nothing. Product naming is
inconsistent *within the same array* — `AWS Security Agent` has spaces, `AWSDevOpsAgent` does not. Treat
these as opaque identifiers; never build the match string from a product's display name.

`applicableProductNames` is optional and may be absent. Absence is **undefined** — do not read it as
"covers everything." Report coverage as unknown.

### Four traps

**1. `creditStatus` is not a usability signal.** Fully exhausted credits still report `ENABLED` — observed
on all four live credits, every one with `remainingAmount: 0` and an `exhaustDate` set. Always gate on
`remainingAmount > 0`.

**2. `creditType` cannot identify Activate credits.** Free Tier and Explore AWS credits are both
`Promotion` — identical to how Activate credits appear. There is no Activate value, and the API reference
lists `Promotion` / `Refund` / `TrueUp` as *examples*, not a closed enum.

Use `description` to name a credit. It is `Required: Yes` so it is always present, and it carries the
program name: `"AWS Free Tier"`, `"Explore AWS: Launch an instance using EC2"`. Say what the credit calls
itself. **Never assert "Activate credits" unless the description says so.**

**3. `applicationType` does not match its documented enum.** Docs give
`Valid Values: BEFORE_CROSS_SERVICE_DISCOUNTS | AFTER_DISCOUNTS`. The observed value is `AfterDiscounts`.

**4. Dates are ISO 8601 strings through the CLI**, not the epoch seconds the API reference describes.

## What to report

Aggregate across credits where `remainingAmount > 0` and `creditStatus == "ENABLED"`.

- **Covered** — *"You have $X in {description} credits, expiring {date}. They cover AWS DevOps Agent."*
- **Not covered** — *"You have $X in credits, but they don't cover AWS DevOps Agent. Usage will bill to
  your payment method at about $29.88 per agent-hour."*
- **No usable credits** — *"You have no credits with a remaining balance. Usage bills at about $29.88 per
  agent-hour."*
- **Cannot read** — the root-user message above.

If a credit with a balance expires within 30 days, mention it. Unused credits expiring is worth a founder's
attention on its own, independent of anything to do with DevOps Agent.

## Cost

No per-request charge is documented for `GetCredits` — unlike Cost Explorer, which states $0.01 per
paginated request explicitly. Do not substitute Cost Explorer for this; it costs money, its data is at
least 24 hours stale, and enabling it on an account is **irreversible**.
