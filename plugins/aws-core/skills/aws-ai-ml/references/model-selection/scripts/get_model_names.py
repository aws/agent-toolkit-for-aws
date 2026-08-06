import json
import sys

import boto3

if len(sys.argv) < 2:
    print("Usage: python get_model_names.py <hub-name> [region]")
    sys.exit(1)

hub_name = sys.argv[1]
region_name = sys.argv[2] if len(sys.argv) > 2 else None

sm_client = boto3.client("sagemaker", region_name=region_name)

# Retrieve all models with pagination
all_contents = []
next_token = None

while True:
    params = {"HubName": hub_name, "HubContentType": "Model", "MaxResults": 100}

    if next_token:
        params["NextToken"] = next_token

    response = sm_client.list_hub_contents(**params)
    all_contents.extend(response.get("HubContentSummaries", []))

    next_token = response.get("NextToken")
    if not next_token:
        break

# Filter for customization-capable models
customization_models = [
    content
    for content in all_contents
    if "@capability:customization" in content.get("HubContentSearchKeywords", [])
]

model_names = [m.get("HubContentName") for m in customization_models]

print(json.dumps(model_names))
