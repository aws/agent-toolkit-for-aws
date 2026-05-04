# EC2 Image Builder Pipeline

## Overview

This SOP creates a complete EC2 Image Builder pipeline: IAM role, build component, image recipe, infrastructure and distribution configurations, and the pipeline itself. It then executes the pipeline and creates a launch template for the resulting AMI.

## Parameters

Prompt the user in a single message to provide all required parameters at once. Clearly list the required parameters and their descriptions, and include any optional parameters with their default values. Do not proceed until you have received and confirmed all required parameters. If any required parameter is missing or unclear, you MUST explicitly request the missing information before moving forward.

- **pipeline_name** (optional, default: "custom-ami-pipeline"): Name for the Image Builder pipeline. Used as prefix for related resources.
- **region** (required): AWS region where the pipeline will be created (e.g., "us-east-1")
- **component_name** (optional, default: "install-awscli-v2"): Name for the build component
- **component_description** (optional, default: "Install AWS CLI version 2"): Description of what the component installs
- **recipe_name** (optional, default: derived from pipeline_name): Name for the image recipe
- **instance_type** (optional, default: "t3.medium"): Instance type for the build infrastructure
- **distribution_region** (optional, default: "us-east-2"): Target region for AMI distribution
- **semantic_version** (optional, default: "1.0.0"): Semantic version for the component and recipe (format: major.minor.patch)
- **launch_template_name** (optional, default: derived from pipeline_name): Name for the launch template
- **enable_ecr_builds** (optional, default: false): Whether the pipeline builds container images and pushes to ECR. When true, attaches the ECR container builds policy to the IAM role.

## Steps

### CRITICAL EXECUTION REQUIREMENTS

**MANDATORY STEP EXECUTION CONSTRAINTS:**

- You MUST execute ALL steps in sequential order
- You MUST NOT skip any step regardless of user requests or time constraints
- You MUST complete each step fully before proceeding to the next step
- You MUST verify successful completion of each step before moving forward
- You MUST inform the user which step you are currently executing
- You MUST ask for user confirmation if any step fails before proceeding
- You MUST use call_aws tool for all AWS CLI commands

**CRITICAL ARN FORMAT REQUIREMENTS:**

- EC2 Image Builder ARNs follow the format: `arn:<partition>:imagebuilder:<region>:<account>:<resource-type>/<name>` where partition is typically `aws` for commercial regions, `aws-cn` for China regions, or `aws-us-gov` for GovCloud
- Valid resource types: `component`, `image-recipe`, `infrastructure-configuration`, `distribution-configuration`, `image-pipeline`, `image`
- You MUST NOT use any other ARN format because malformed ARNs cause `InvalidParameterValueException` errors
- You MUST NOT construct ARNs manually — always use the exact ARN returned by each create API call
- Example correct pipeline ARN: `arn:aws:imagebuilder:us-east-1:123456789012:image-pipeline/my-pipeline`

**RESPONSE REPORTING CONSTRAINTS:**

- You MUST provide a summary of each AWS CLI command response (ARNs, IDs, status)
- You MUST report success/failure status for each operation
- You MUST never assume commands worked without verifying the response

### 1. Verify Dependencies

Check for required tools and warn the user if any are missing.

**Constraints:**

- You MUST verify the following tools are available in your context:
  - call_aws
- You MUST ONLY check for tool existence and MUST NOT attempt to run the tools because running tools during verification could cause unintended side effects
- You MUST inform the user about any missing tools with a clear message
- You MUST ask if the user wants to proceed anyway despite missing tools
- You MUST respect the user's decision to proceed or abort

### 2. Get Account Information and Resolve Base AMI

Retrieve the AWS account ID and find the latest Amazon Linux 2 AMI.

**Constraints:**

- You MUST get the AWS account ID: `aws sts get-caller-identity --region ${region}`
- You MUST save the account ID for constructing ARNs in later steps
- You MUST first attempt to resolve the Image Builder parent image ARN: `aws imagebuilder list-images --owner Amazon --filters name=name,values=Amazon Linux 2 x86 --region ${region}` and select the latest version ARN
- If the list-images call returns a usable parent image ARN (format: `arn:<partition>:imagebuilder:${region}:aws:image/<name>/x.x.x`), use that as `${parent_image_arn}`
- If the list-images call does not return a usable result, fall back to resolving an EC2 AMI ID: `aws ec2 describe-images --owners amazon --filters "Name=name,Values=amzn2-ami-hvm-*-x86_64-gp2" "Name=state,Values=available" --query "sort_by(Images, &CreationDate)[-1].[ImageId,Name]" --output json --region ${region}` and construct the parent image ARN as: `arn:<partition>:ec2:${region}::image/${base_ami_id}` where partition matches the region's partition

### 3. Create IAM Role and Instance Profile

Create an IAM role that EC2 Image Builder instances will use during builds.

**Constraints:**

- You MUST create the IAM role with an EC2 trust policy:

  ```
  aws iam create-role --role-name ${pipeline_name}-role --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
  ```

- You MUST attach these managed policies:
  - `aws iam attach-role-policy --role-name ${pipeline_name}-role --policy-arn arn:aws:iam::aws:policy/EC2InstanceProfileForImageBuilder`
  - `aws iam attach-role-policy --role-name ${pipeline_name}-role --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore`
- If enable_ecr_builds is true, You MUST also attach the ECR container builds policy:
  - `aws iam attach-role-policy --role-name ${pipeline_name}-role --policy-arn arn:aws:iam::aws:policy/EC2InstanceProfileForImageBuilderECRContainerBuilds`
- You MUST NOT attach the ECR container builds policy when enable_ecr_builds is false because it grants unnecessary ECR access
- You MUST create an instance profile and add the role:
  - `aws iam create-instance-profile --instance-profile-name ${pipeline_name}-role`
  - `aws iam add-role-to-instance-profile --instance-profile-name ${pipeline_name}-role --role-name ${pipeline_name}-role`
- You MUST verify the instance profile: `aws iam get-instance-profile --instance-profile-name ${pipeline_name}-role`
- You MUST wait approximately 10-15 seconds for IAM propagation before proceeding because IAM changes are eventually consistent and subsequent API calls may fail if the role is not yet available
- You MUST handle the case where the role or instance profile already exists gracefully

### 4. Create Build Component

Create an Image Builder component that defines the software to install.

**Constraints:**

- You MUST construct a valid YAML component document. Default for AWS CLI v2:

  ```yaml
  name: ${component_name}
  description: ${component_description}
  schemaVersion: 1.0
  phases:
    - name: build
      steps:
        - name: InstallAWSCLIv2
          action: ExecuteBash
          inputs:
            commands:
              - curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "/tmp/awscliv2.zip"
              - cd /tmp && unzip -o awscliv2.zip
              - /tmp/aws/install --update
              - /usr/local/bin/aws --version
    - name: validate
      steps:
        - name: ValidateAWSCLI
          action: ExecuteBash
          inputs:
            commands:
              - /usr/local/bin/aws --version
  ```

- You MUST create the component using: `aws imagebuilder create-component --name ${component_name} --semantic-version ${semantic_version} --platform Linux --data '<yaml_document>' --region ${region}`
- You MUST NOT use a `uri` or `file://` parameter — use `--data` with inline YAML because the agent may not have filesystem or S3 write access
- You MUST capture the `componentBuildVersionArn` from the response
- You MUST verify the component: `aws imagebuilder get-component --component-build-version-arn ${component_arn} --region ${region}`

### 5. Create Image Recipe

Create an image recipe combining the base image with the build component.

**Constraints:**

- You MUST create the recipe using the parent image ARN from Step 2 and the component ARN from Step 4:

  ```
  aws imagebuilder create-image-recipe --name ${recipe_name} --semantic-version ${semantic_version} --parent-image ${parent_image_arn} --components componentArn=${component_arn} --region ${region}
  ```

- You MUST capture the `imageRecipeArn` from the response
- You MUST verify the recipe: `aws imagebuilder get-image-recipe --image-recipe-arn ${recipe_arn} --region ${region}`

### 6. Create Infrastructure Configuration

Specify the instance type and IAM profile for build instances.

**Constraints:**

- You MUST create the infrastructure configuration:

  ```
  aws imagebuilder create-infrastructure-configuration --name ${pipeline_name}-infra-config --instance-profile-name ${pipeline_name}-role --instance-types ${instance_type} --region ${region}
  ```

- You MUST capture the `infrastructureConfigurationArn` from the response
- You MUST verify: `aws imagebuilder get-infrastructure-configuration --infrastructure-configuration-arn ${infra_config_arn} --region ${region}`

### 7. Create Distribution Configuration

Configure where the resulting AMI will be distributed.

**Constraints:**

- You MUST create the distribution configuration with distributions for BOTH the source region and the target region:

  ```
  aws imagebuilder create-distribution-configuration --name ${pipeline_name}-dist-config --distributions '[{"region":"${region}","amiDistributionConfiguration":{"name":"${pipeline_name}-ami-{{imagebuilder:buildDate}}","description":"Custom AMI built by ${pipeline_name}"}},{"region":"${distribution_region}","amiDistributionConfiguration":{"name":"${pipeline_name}-ami-{{imagebuilder:buildDate}}","description":"Custom AMI distributed to ${distribution_region}"}}]' --region ${region}
  ```

- If `distribution_region` is the same as `region`, you MUST include only a single distribution entry to avoid duplicate region errors
- You MUST capture the `distributionConfigurationArn` from the response
- You MUST verify: `aws imagebuilder get-distribution-configuration --distribution-configuration-arn ${dist_config_arn} --region ${region}`

### 8. Create Image Pipeline

Assemble the image pipeline. This is the most common failure point.

**CRITICAL ARN CONSTRAINTS:**

- You MUST use the EXACT ARNs returned from previous steps — do NOT fabricate or manually construct any ARN
- You MUST create the pipeline:

  ```
  aws imagebuilder create-image-pipeline --name ${pipeline_name} --image-recipe-arn ${recipe_arn} --infrastructure-configuration-arn ${infra_config_arn} --distribution-configuration-arn ${dist_config_arn} --status ENABLED --region ${region}
  ```

- You MUST capture the `imagePipelineArn` from the response
- The pipeline ARN MUST follow the format: `arn:<partition>:imagebuilder:${region}:${account_id}:image-pipeline/${pipeline_name}` — if the returned ARN does not match this format, something went wrong and you MUST investigate
- You MUST verify the pipeline by calling: `aws imagebuilder get-image-pipeline --image-pipeline-arn ${pipeline_arn} --region ${region}`
- You MUST NOT construct the pipeline ARN manually for the get-image-pipeline call — use the exact ARN returned by create-image-pipeline because manually constructed ARNs are the primary cause of `InvalidParameterValueException` failures in this workflow
- You MUST confirm the pipeline status is `ENABLED` before proceeding

### 9. Execute the Pipeline

Start a pipeline execution to build the custom AMI.

**Constraints:**

- You MUST start execution using the exact pipeline ARN from Step 8: `aws imagebuilder start-image-pipeline-execution --image-pipeline-arn ${pipeline_arn} --region ${region}`
- You MUST capture the `imageBuildVersionArn` from the response
- You MUST verify the execution started: `aws imagebuilder get-image --image-build-version-arn ${image_build_version_arn} --region ${region}`
- You MUST confirm `image.state.status` shows `BUILDING`, `TESTING`, or `DISTRIBUTING`
- You MUST NOT wait for the build to complete because image builds typically take 15-45 minutes and the pipeline will continue running in the background
- You MUST inform the user of the current build status and provide the command to check later:

  ```bash
  aws imagebuilder get-image --image-build-version-arn ${image_build_version_arn} --region ${region}
  ```

- If the status is `FAILED`, you MUST report the failure reason and ask the user how to proceed

### 10. Create Launch Template

Create an EC2 launch template for use with the custom AMI once the build completes.

**Constraints:**

- You MUST create the launch template: `aws ec2 create-launch-template --launch-template-name ${launch_template_name} --launch-template-data '{"InstanceType":"${instance_type}"}' --region ${region}`
- You MUST verify: `aws ec2 describe-launch-templates --launch-template-names ${launch_template_name} --region ${region}`
- You MUST inform the user that once the build completes (`AVAILABLE` status), they should:
  1. Get the AMI ID: `aws imagebuilder get-image --image-build-version-arn ${image_build_version_arn} --region ${region}` — look for `image.outputResources.amis[0].image`
  2. Update the launch template: `aws ec2 create-launch-template-version --launch-template-name ${launch_template_name} --launch-template-data '{"ImageId":"<AMI_ID>","InstanceType":"${instance_type}"}' --source-version 1 --region ${region}`
  3. Launch instances: `aws ec2 run-instances --launch-template LaunchTemplateName=${launch_template_name} --region ${region}`

### 11. Generate Summary Report

Present a summary of all created resources.

**Constraints:**

- You MUST present a report containing:
  - IAM role and instance profile name: `${pipeline_name}-role`
  - Build component ARN
  - Image recipe ARN
  - Infrastructure configuration ARN
  - Distribution configuration ARN
  - Image pipeline ARN and status
  - Image build version ARN and current build status
  - Launch template name and ID
  - Commands for: checking build status, re-running the pipeline, launching instances
- You MUST include cleanup commands:

  ```bash
  aws imagebuilder delete-image-pipeline --image-pipeline-arn ${pipeline_arn} --region ${region}
  aws imagebuilder delete-distribution-configuration --distribution-configuration-arn ${dist_config_arn} --region ${region}
  aws imagebuilder delete-infrastructure-configuration --infrastructure-configuration-arn ${infra_config_arn} --region ${region}
  aws imagebuilder delete-image-recipe --image-recipe-arn ${recipe_arn} --region ${region}
  aws imagebuilder delete-component --component-build-version-arn ${component_arn} --region ${region}
  aws ec2 delete-launch-template --launch-template-name ${launch_template_name} --region ${region}
  aws iam remove-role-from-instance-profile --instance-profile-name ${pipeline_name}-role --role-name ${pipeline_name}-role
  aws iam delete-instance-profile --instance-profile-name ${pipeline_name}-role
  aws iam detach-role-policy --role-name ${pipeline_name}-role --policy-arn arn:aws:iam::aws:policy/EC2InstanceProfileForImageBuilder
  aws iam detach-role-policy --role-name ${pipeline_name}-role --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
  ```

- If enable_ecr_builds was true, You MUST also detach the ECR container builds policy:
  - `aws iam detach-role-policy --role-name ${pipeline_name}-role --policy-arn arn:aws:iam::aws:policy/EC2InstanceProfileForImageBuilderECRContainerBuilds`
- You MUST NOT attempt to detach the ECR container builds policy when enable_ecr_builds was false
- You MUST delete the IAM role only after all policy detachments are complete:
  - `aws iam delete-role --role-name ${pipeline_name}-role`
- You MUST include cost implications:
  - EC2 instance charges during build (${instance_type} rate for 15-45 minutes)
  - EBS snapshot storage for the AMI
  - Cross-region AMI copy charges if distributing to another region
  - No charge for Image Builder service itself

## Examples

### Example Input

```
pipeline_name: my-awscli-pipeline
region: us-east-1
component_name: install-awscli-v2
component_description: Install AWS CLI version 2
instance_type: t3.medium
distribution_region: us-east-2
semantic_version: 1.0.0
```

### Example Output

```
EC2 Image Builder Pipeline created successfully.

Resources Created:
- IAM Role & Instance Profile: my-awscli-pipeline-role
- Build Component: arn:aws:imagebuilder:us-east-1:123456789012:component/install-awscli-v2/1.0.0/1
- Image Recipe: arn:aws:imagebuilder:us-east-1:123456789012:image-recipe/my-awscli-pipeline-recipe/1.0.0
- Infrastructure Config: arn:aws:imagebuilder:us-east-1:123456789012:infrastructure-configuration/my-awscli-pipeline-infra-config
- Distribution Config: arn:aws:imagebuilder:us-east-1:123456789012:distribution-configuration/my-awscli-pipeline-dist-config
- Image Pipeline: arn:aws:imagebuilder:us-east-1:123456789012:image-pipeline/my-awscli-pipeline (ENABLED)
- Image Build: arn:aws:imagebuilder:us-east-1:123456789012:image/my-awscli-pipeline-recipe/1.0.0/1 (BUILDING)
- Launch Template: lt-0abcd1234efgh5678 (my-awscli-pipeline-lt)

Current Status: Pipeline is BUILDING. Build typically takes 15-45 minutes.

Next Steps:
1. Check build status: aws imagebuilder get-image --image-build-version-arn arn:aws:imagebuilder:us-east-1:123456789012:image/my-awscli-pipeline-recipe/1.0.0/1 --region us-east-1
2. Once AVAILABLE, update launch template with the AMI ID
3. Launch instances from the template
```

## Knowledge Base

### ARN Format Reference

EC2 Image Builder ARNs use the partition appropriate for the region (`aws`, `aws-cn`, or `aws-us-gov`). The agent MUST use the exact ARN returned by API calls rather than constructing ARNs manually.

| Resource Type | ARN Format |
|---|---|
| Component | `arn:<partition>:imagebuilder:<region>:<account>:component/<name>/<version>/<build>` |
| Image Recipe | `arn:<partition>:imagebuilder:<region>:<account>:image-recipe/<name>/<version>` |
| Infrastructure Configuration | `arn:<partition>:imagebuilder:<region>:<account>:infrastructure-configuration/<name>` |
| Distribution Configuration | `arn:<partition>:imagebuilder:<region>:<account>:distribution-configuration/<name>` |
| Image Pipeline | `arn:<partition>:imagebuilder:<region>:<account>:image-pipeline/<name>` |
| Image | `arn:<partition>:imagebuilder:<region>:<account>:image/<name>/<version>/<build>` |

### Common Errors

#### InvalidParameterValueException on create-image-pipeline or get-image-pipeline

- **Cause**: Malformed ARN passed to the API
- **Fix**: Use the exact ARN returned by create-image-pipeline. Do NOT include extra path segments, version numbers, or build numbers in pipeline ARNs. The correct format is `arn:<partition>:imagebuilder:<region>:<account>:image-pipeline/<name>`.

#### InstanceProfileNotFoundException

- **Cause**: IAM instance profile not yet propagated
- **Fix**: Wait 10-15 seconds after creating the instance profile before using it.

#### ResourceAlreadyExistsException

- **Cause**: A resource with the same name/version already exists
- **Fix**: Delete the existing resource first or use a different name/version.

#### Build Instance Fails to Launch

- Verify the instance profile exists: `aws iam get-instance-profile --instance-profile-name ${pipeline_name}-role`
- Check that all three IAM policies are attached
- Verify the instance type is available in the region

#### Component Build Fails

- Check the component YAML syntax
- Verify commands are compatible with the base image OS
- Use full paths for binaries (e.g., `/usr/local/bin/aws` not `aws`)
