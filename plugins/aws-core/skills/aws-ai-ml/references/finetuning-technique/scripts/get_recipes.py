import json
import os
import sys

import boto3

os.environ.setdefault("AWS_SDK_UA_APP_ID", "AWSSkill-SageMaker")

if len(sys.argv) < 3:
    print("Usage: python get_recipes.py <model-name> <hub-name>")
    sys.exit(1)

model_name = sys.argv[1]
hub_name = sys.argv[2]
sm_client = boto3.client("sagemaker")

detail = sm_client.describe_hub_content(
    HubName=hub_name, HubContentType="Model", HubContentName=model_name
)

keywords = detail.get("HubContentSearchKeywords", [])

# Only include SFT, DPO, RLVR, and RLAIF techniques
supported = {"sft", "dpo", "rlvr", "rlaif"}
techniques = sorted(
    t.replace("@recipe:finetuning_", "").split("_")[0]
    for t in keywords
    if t.startswith("@recipe:finetuning_")
)
techniques = [t for t in dict.fromkeys(techniques) if t in supported]

print(json.dumps(techniques))
