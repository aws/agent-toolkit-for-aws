# Serverless Model Customization and Data Preparation Region Availability

Single source of truth for the AWS regions where serverless model customization
(fine-tuning) and the data preparation skills (synthetic-dataset-generation,
dataset-quality, dataset-transformation, auto-labeling) are available. These
references point here rather than repeating the list, so it only needs to be
updated in one place.

## Serverless model customization (fine-tuning)

Serverless model customization is supported in:

| Region code | Location |
| --- | --- |
| `us-west-2` | Oregon |
| `us-east-1` | N. Virginia |
| `ap-northeast-1` | Tokyo |
| `eu-west-1` | Ireland |

> This list may expand over time. See the
> [SageMaker serverless model customization documentation](https://docs.aws.amazon.com/sagemaker/latest/dg/customize-model.html)
> for the latest availability.

### Blocking message — fine-tuning (use verbatim when the region is unsupported)

> "Serverless model customization is not available in your region
> (`<region>`). It is supported in: us-west-2, us-east-1,
> ap-northeast-1, and eu-west-1. I can help you deploy a base model instead, or
> you can switch to a supported region and try again."

## Data preparation skills (synthetic-dataset-generation, dataset-quality, dataset-transformation, auto-labeling)

The data preparation skills are supported in:

| Region code | Location |
| --- | --- |
| `us-east-1` | N. Virginia |
| `us-west-2` | Oregon |

> This list may expand over time. See the
> [SageMaker AI Region availability docs](https://docs.aws.amazon.com/sagemaker/latest/dg/regions-quotas.html)
> for the latest availability.

### Blocking message — pure data preparation plans

> "Data preparation (synthetic dataset generation, dataset quality, dataset
> transformation, auto-labeling) is not available in your region
> (`<region>`). It is supported in: us-east-1 and us-west-2. You can switch
> to a supported region and try again."

### Step-exclusion message — mixed plans

> "Your region (`<region>`) supports fine-tuning but not data preparation
> (synthetic dataset generation, dataset quality, dataset transformation,
> auto-labeling), which is available only in us-east-1 and us-west-2. I will
> exclude the data preparation steps from the plan and continue with the
> fine-tuning path — please bring your own prepared dataset."
