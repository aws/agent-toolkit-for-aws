# Common Pitfalls

## Assuming Direct Name Mapping

API operation names and IAM action names frequently differ. Always query the service authorization reference.

```json
{
  "Action": "dynamodb:QueryItems"
}
```

Wrong — the correct action is `dynamodb:Query`.

## Missing Required Actions for an Operation

Some operations require multiple IAM actions. For example, `dynamodb:BatchExecuteStatement` requires `dynamodb:PartiQLDelete`, `dynamodb:PartiQLInsert`, `dynamodb:PartiQLSelect`, and `dynamodb:PartiQLUpdate`.

## Using Wildcard Resources Unnecessarily

```json
{
  "Action": "s3:GetObject",
  "Resource": "*"
}
```

Too broad. Specify bucket and object paths: `arn:aws:s3:::my-bucket/*`.

## ForAnyValue/ForAllValues on Non-Array Condition Keys

`ForAnyValue` and `ForAllValues` MUST only be used with array-typed condition keys.

**Check the type** using the service reference `ConditionKeys` array:

- **Array types** (safe for set operators): `ArrayOfString`, `ArrayOfARN`, `ArrayOfNumeric`
  - Examples: `aws:TagKeys`, `dynamodb:Attributes`, `dynamodb:LeadingKeys`
- **Scalar types** (do NOT use set operators): `String`, `Bool`, `ARN`, `Numeric`
  - Examples: `dynamodb:EnclosingOperation`, `dynamodb:FullTableScan`

## ForAnyValue in Deny Statements Without Null Check

`ForAnyValue` evaluates to `FALSE` when the context key does not exist. Deny statements using `ForAnyValue` will not block requests when the key is missing.

❌ **Incorrect:**

```json
{
  "Effect": "Deny",
  "Principal": "*",
  "Action": ["s3:GetObject", "s3:PutObject"],
  "Resource": "arn:aws:s3:::my-bucket/*",
  "Condition": {
    "ForAnyValue:StringNotLike": {
      "aws:VpceOrgPaths": "o-abcdefg/r-12345/ou-123456/*"
    }
  }
}
```

✅ **Correct — add a separate Null-check statement:**

```json
{
  "Effect": "Deny",
  "Principal": "*",
  "Action": ["s3:GetObject", "s3:PutObject"],
  "Resource": "arn:aws:s3:::my-bucket/*",
  "Condition": {
    "ForAnyValue:StringNotLike": {
      "aws:VpceOrgPaths": "o-abcdefg/r-12345/ou-123456/*"
    }
  }
},
{
  "Effect": "Deny",
  "Principal": "*",
  "Action": ["s3:GetObject", "s3:PutObject"],
  "Resource": "arn:aws:s3:::my-bucket/*",
  "Condition": {
    "Null": { "aws:VpceOrgPaths": "true" }
  }
}
```

## ForAllValues in Allow Statements Without Null Check

`ForAllValues` evaluates to `TRUE` when the context key does not exist. Allow statements using `ForAllValues` will grant access when the key is missing.

❌ **Incorrect:**

```json
{
  "Effect": "Allow",
  "Action": "s3:PutObject",
  "Resource": "*",
  "Condition": {
    "ForAllValues:StringEquals": { "aws:TagKeys": "a" }
  }
}
```

✅ **Correct — require the key to exist:**

```json
{
  "Effect": "Allow",
  "Action": "s3:PutObject",
  "Resource": "*",
  "Condition": {
    "Null": { "aws:TagKeys": "false" },
    "ForAllValues:StringEquals": { "aws:TagKeys": "a" }
  }
}
```

`ForAllValues` in Allow statements is risky. If you must use it, always combine with `Null: false`.

## Case-Sensitive Matching on aws:TagKeys in Tag-Protection Deny Statements

Tag keys are matched with different case rules depending on where they appear in a condition:

- `aws:TagKeys` carries tag keys as **values**. `StringEquals` and `StringLike` compare values case-sensitively, so `"aws:TagKeys": "protected-tag"` does NOT match a request tag key `PROTECTED-TAG`.
- In `aws:PrincipalTag/<key>`, `aws:ResourceTag/<key>`, and `aws:RequestTag/<key>`, the tag key is part of the **condition key name**, and condition key names are case-insensitive. `aws:PrincipalTag/protected-tag` matches a principal tag named `protected-tag`, `Protected-Tag`, or `PROTECTED-TAG`.

A Deny that protects an authorization tag with a case-sensitive operator therefore does not work as expected: the principal supplies a re-cased key, the Deny does not fire, and every policy that reads the tag via `aws:PrincipalTag`/`aws:ResourceTag` still matches it.

❌ **Incorrect — bypassed by tagging with `PROTECTED-TAG` (or any other casing):**

```json
{
  "Effect": "Deny",
  "Action": ["iam:TagRole", "iam:UntagRole", "iam:TagUser", "iam:UntagUser"],
  "Resource": "*",
  "Condition": {
    "ForAnyValue:StringEquals": {
      "aws:TagKeys": "protected-tag"
    }
  }
}
```

✅ **Correct — use the case-insensitive operator:**

```json
{
  "Effect": "Deny",
  "Action": ["iam:TagRole", "iam:UntagRole", "iam:TagUser", "iam:UntagUser"],
  "Resource": "*",
  "Condition": {
    "ForAnyValue:StringEqualsIgnoreCase": {
      "aws:TagKeys": "protected-tag"
    }
  }
}
```

Rules for this pattern:

1. `StringLike` has no `IgnoreCase` variant. Do not protect tag keys with wildcard patterns — list the exact key names with `StringEqualsIgnoreCase` instead.
2. Do not add a companion `Null` Deny statement (unlike the `ForAnyValue:StringNotLike` pattern above). This Deny is meant to fire only when a protected key is present; denying when `aws:TagKeys` is absent would block every untagged request for those actions.
3. Case-sensitive matching is acceptable when the operator selects the keys to **permit** (`Allow` + `ForAllValues:StringEquals` on `aws:TagKeys`): a re-cased key is simply outside the allowlist, so do not switch an allowlist to `StringEqualsIgnoreCase`. That Allow still needs the `Null: {"aws:TagKeys": "false"}` condition from the section above — `ForAllValues` alone evaluates to true when the request carries no tag keys, which would allow untagged requests.

## Adding Conditions When They Are Not Needed

For identity policies, most policies only need Actions and Resources. Add conditions only when:

- Restricting sensitive actions (e.g., requiring MFA for `iam:DeleteUser`)
- Implementing tag-based access control (TBAC)
- Enforcing organizational requirements (encryption, VPC restrictions)

Resource policies more commonly use conditions (VPC endpoints, source IPs, secure transport).
