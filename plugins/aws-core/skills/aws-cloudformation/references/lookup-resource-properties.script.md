# Lookup CloudFormation Resource Properties

## Overview

Deterministic procedure for looking up the authoritative schema for a CloudFormation resource type: property names, types, which are required vs. optional, valid enum values, and return values for `!GetAtt`. Use when authoring or modifying a template and you need to avoid guessing at property names.

## Parameters

- **resource_type** (required): The full CloudFormation resource type (e.g., `AWS::Lambda::Function`, `AWS::S3::Bucket`, `AWS::DynamoDB::Table`).
- **focus** (optional): Specific aspect to look up. One of:
  - `properties` (default) — all properties with types
  - `required` — only required properties
  - `return-values` — what `!Ref` and `!GetAtt` return
  - `property:<PropertyName>` — deep-dive on a single property including nested sub-properties

**Constraints for parameter acquisition:**

- You MUST ask for the resource type upfront if not provided
- You SHOULD infer the resource type from the user's question when possible (e.g., "what properties does a Lambda function have" → `AWS::Lambda::Function`)
- You MUST confirm the inferred resource type with the user before looking up if there is any ambiguity

## Steps

### 1. Verify Dependencies

Check which lookup mechanism is available.

**Constraints:**

- You MUST check for web access (agent's web fetch or equivalent capability) to retrieve the public CloudFormation documentation
- You MUST ONLY check for availability and MUST NOT execute lookups during this step
- If web access is not available, You MUST inform the user that offline lookup requires a locally-cached schema (e.g., `cfn-lint`'s bundled schema via `cfn-lint --info`) and ask whether to use the local fallback or abort

### 2. Construct the Documentation URL

Derive the authoritative CloudFormation documentation URL from the resource type.

**Constraints:**

- You MUST use the URL pattern: `https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-<service>-<resource>.html`
- Examples:
  - `AWS::Lambda::Function` → `aws-resource-lambda-function.html`
  - `AWS::S3::Bucket` → `aws-resource-s3-bucket.html`
  - `AWS::DynamoDB::Table` → `aws-resource-dynamodb-table.html`
- For some older resource types the pattern uses `aws-properties-` instead of `aws-resource-` (e.g., `aws-properties-ec2-securitygroup.html`). If the first URL returns a 404, You MUST try the `aws-properties-` variant
- You MUST NOT guess at schemas from memory because CloudFormation schemas evolve; always consult the authoritative source

### 3. Fetch and Extract the Schema

Retrieve the documentation and extract the relevant sections.

**Constraints:**

- You MUST fetch the documentation page
- You MUST extract, based on the `focus` parameter:
  - **properties**: the "Properties" section with each property's name, required/optional status, type, allowed values, update requirements
  - **required**: only properties marked "Required: Yes"
  - **return-values**: the "Return values" section covering `!Ref` and `!GetAtt` attributes
  - **property:`<Name>`**: the sub-sections describing that property's nested schema
- You MUST preserve the exact property names (case-sensitive) because CloudFormation rejects misspelled property names
- You MUST capture type information (String, Integer, Boolean, List, or a sub-type link) because type mismatches are a leading cause of deployment failures
- You SHOULD capture the "Update requires" column because users often care whether a property change triggers replacement vs. modification

### 4. Present the Results

Return the schema information in a format that is directly usable for template authoring.

**Constraints:**

- You MUST present properties as a table or bullet list with columns/fields: Name, Required, Type, Default (if any), Allowed Values (if an enum), Update Requires
- For the `required` focus, You MUST list ONLY required properties and explicitly state "the remaining properties are optional" rather than omitting them silently
- For complex nested types, You MUST link to the nested type's documentation URL so the user can dig deeper
- You SHOULD include a minimal YAML example using the looked-up properties, because examples save the user from assembling them manually
- You MUST cite the source URL so the user can verify

### 5. Recommend Next Steps

Guide the user on how to use the information.

**Constraints:**

- If the user was authoring a template, You SHOULD offer to draft the resource block using the schema
- You SHOULD recommend running cfn-lint and cfn-guard after authoring because they catch remaining schema and security issues
- If the user asked about a specific property that has nested complex types, You SHOULD offer to recursively look up the nested types on request

## Examples

### Example Input

```
resource_type: AWS::Lambda::Function
focus: required
```

### Example Output

```
Required properties for AWS::Lambda::Function
Source: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-lambda-function.html

| Name    | Type   | Update requires | Notes |
|---------|--------|-----------------|-------|
| Code    | Code   | No interruption | Either ZipFile, S3Bucket+S3Key, or ImageUri |
| Role    | String | No interruption | IAM role ARN (must match ^arn:aws:iam::\d{12}:role/.+$) |

Example:
  MyFunction:
    Type: AWS::Lambda::Function
    Properties:
      Role: !GetAtt MyLambdaRole.Arn
      Code:
        ZipFile: |
          def handler(event, context):
              return {'statusCode': 200}

The remaining properties (Runtime, Handler, etc.) are conditionally required
or optional depending on deployment type. Tell me if you want the full
property list.
```

## Troubleshooting

### Documentation URL returns 404
Some resource types use `aws-properties-` instead of `aws-resource-` in the URL path (historical naming). Try both variants before falling back to search.

### Property schema differs from what I see in the Console
The Console sometimes exposes additional UI-only fields that do not exist in the CloudFormation schema. The documentation is authoritative for CloudFormation property names.

### Ambiguous service name
Some service names are not obvious (e.g., `AWS::IAM::Role` is `iam-role`, but `AWS::EC2::SecurityGroup` is `ec2-securitygroup` — CamelCase words are not split). If the URL derivation fails, search the CloudFormation User Guide for the resource type by its full name.
