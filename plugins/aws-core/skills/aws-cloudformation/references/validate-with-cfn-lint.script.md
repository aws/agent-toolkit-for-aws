# Validate with cfn-lint

## Overview

Deterministic procedure for local CloudFormation template validation with `cfn-lint`. Use this SOP when the user explicitly requests cfn-lint, the project configures it, or it is already installed. Prefer the CLI; the Python API is also available for local validation.

## Parameters

- **template_content** (required): The CloudFormation template as a YAML or JSON string, a file path, or a URL to the template.
- **regions** (optional): List of AWS regions to validate against (e.g., `["us-east-1", "eu-west-1"]`). Defaults to cfn-lint's default region if omitted.
- **ignore_checks** (optional): List of cfn-lint rule IDs to suppress (e.g., `["W2001", "E3012"]`).

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt rather than one at a time
- You MUST support multiple input methods for the template:
  - Direct input: Template content pasted directly in the conversation
  - File path: Path to a local template file
  - URL: Link to a template in a repository or S3
- You MUST use appropriate tools to read the template content based on the input method
- You MUST confirm successful acquisition of the template content before proceeding

## Steps

### 1. Verify Dependencies

Check which validation mechanism is available.

**Constraints:**

- You MUST check in this order of preference:
  1. `cfn-lint` CLI available on the user's system (verify with `which cfn-lint` or `cfn-lint --version`)
  2. Python `cfnlint` library (verify by attempting `import cfnlint` in a throwaway Python command)
- If cfn-lint is not installed, You MUST consult the [cfn-lint installation documentation](https://github.com/aws-cloudformation/cfn-lint#install) and authoritative package registry, resolve a compatible release, and ask the user: "I can install the exact cfn-lint version `<resolved-version>` from PyPI. Do you want me to install it, or would you prefer to install it manually?"
- You MUST install ONLY the exact user-approved `cfn-lint` version from PyPI, with no extra packages. If installation is not possible — pip missing, PyPI unreachable, or the user declines — You MUST NOT attempt another cfn-lint installation mechanism. Tell the user that cfn-lint cannot run, note the reduced local validation coverage, and ask whether to use the [cloudformation-validate SOP](validate-with-cloudformation-validate.script.md) as the alternate local validator or stop.
- When a supported cfn-lint mechanism is available, You SHOULD proceed with local validation without asking the user to opt in
- You MUST NOT run an install command without the user's explicit approval because it changes the user's environment
- If no cfn-lint mechanism is available and the user declines both installation and the alternate local validator, You MUST stop and state that local validation did not run
- You MUST respect the user's decision to proceed, install, or abort

### 2. Acquire Template Content

Obtain the CloudFormation template from the user.

**Constraints:**

- You MUST ask the user which template(s) to validate even if templates are discoverable in the working directory, because the user may only want a subset validated
- You MUST read the template content from the provided source (file path, direct input, or URL)
- You MUST confirm the template is non-empty and parseable as YAML or JSON before proceeding
- If the template cannot be read or parsed, You MUST inform the user with the specific error and stop

### 3. Run Validation

Execute cfn-lint against the template using the best available mechanism.

**Constraints:**

- If `cfn-lint` CLI is available, You MUST invoke it on the template file with appropriate flags:
  - Regions: `--regions us-east-1 eu-west-1`
  - Ignore checks: `--ignore-checks W2001 E3012`
  - Output format: `--format json` for structured output
  - Example: `cfn-lint --format json --regions us-east-1 template.yaml`
- Otherwise, if the Python `cfnlint` library is available, You MUST invoke `cfnlint.api.lint(s=template_content, config={"regions": [...], "ignore_checks": [...]})`
- You MUST NOT modify the template content before validation because the user needs to see errors against their actual template
- You MUST capture validator output for local parsing, including rule IDs, severity levels (E=error, W=warning, I=info), line numbers, and messages

### 4. Present Results

Report validation findings to the user.

**Constraints:**

- You MUST start the summary with the total count: "Your template has X errors, Y warnings, Z info messages"
- You MUST group related issues by resource or template section (e.g., all `MyBucket` errors together)
- You MUST prioritize errors first, then warnings, then informational messages
- You MUST include the rule ID, line number, and property path for each issue so the user can locate it
- For each error, You MUST provide the specific YAML/JSON fix showing the corrected property
- You SHOULD use inline comments in code fixes to explain why each change is needed
- For similar errors across multiple resources, You SHOULD show the pattern once with the list of affected resources
- If the template is valid with no issues, You MUST confirm this clearly

### 5. Recommend Next Steps

Guide the user on what to do after validation.

**Constraints:**

- If errors were found, You MUST recommend fixing all errors before proceeding to other checks
- Once the template is error-free, You SHOULD run the [cfn-guard security and compliance SOP](check-cloudformation-template-compliance.script.md) by default to check security and compliance
- You MUST skip the security and compliance SOP only when the user explicitly requests it or confirms that an equivalent project security and compliance check already passed
- You MUST explain what each recommended next step does so the user can make an informed decision

## Security Considerations

Follow the [shared security guidance](security-considerations.md) when handling templates, outputs, secrets, tools, and installation artifacts.

## Examples

### Example Input

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Resources:
  MyFunction:
    Type: AWS::Lambda::Function
    Properties:
      FunctionNam: my-function
      Runtime: python3.9
      Handler: index.handler
      Role: arn:aws:iam::123456789012:role/my-function-role
      Code:
        ZipFile: |
          def handler(event, context):
              return {'statusCode': 200}
```

### Example Output

```
Your template has 1 error, 0 warnings, 0 info messages.

**MyFunction (AWS::Lambda::Function):**
- E3002 at line 6: Invalid Property Resources/MyFunction/Properties/FunctionNam

Fix (line 6):
  FunctionName: my-function  # Typo: FunctionNam → FunctionName
```

## Troubleshooting

### Template fails to parse
If the tool or CLI returns a parsing error, the template has invalid YAML or JSON syntax. Check for indentation issues, missing colons, or unquoted special characters. Fix the syntax and re-run validation.

### Unexpected rule violations
If cfn-lint reports errors you believe are incorrect, suppress specific rules using `ignore_checks`. Verify the rule ID from the output (e.g., `W2001`) and pass it in the parameter.

### Region-specific failures
Some resource properties are only valid in certain regions. If you see region-related errors, pass the target deployment region in the `regions` parameter to get accurate validation.

### cfn-lint not installed
Resolve a compatible cfn-lint release from the official installation documentation and authoritative PyPI metadata, then install that exact user-approved version. Do not encode a version range in this SOP. If installation is not possible (pip missing, PyPI unreachable, or the user declines), do not try another cfn-lint installation mechanism. Ask whether to use the [cloudformation-validate SOP](validate-with-cloudformation-validate.script.md) as the alternate local validator or stop. Never report the template as locally validated when no local validator ran.
