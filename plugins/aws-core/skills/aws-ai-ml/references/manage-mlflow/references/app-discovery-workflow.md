# App Discovery Workflow

Discovers existing MLflow apps in the user's account and helps them select one.

> **IMPORTANT:** Use only the MLflow **App** APIs (`ListMlflowApps`, `DescribeMlflowApp`, `CreateMlflowApp`, etc.). Do NOT use the legacy MLflow **Tracking Server** APIs (`ListMlflowTrackingServers`, `CreateMlflowTrackingServer`, `DescribeMlflowTrackingServer`, etc.) — those are deprecated for new deployments.

## Steps

1. Use `aws-mcp` to call `sagemaker:ListMlflowApps` in the current region.

2. **Filter results:**
   - Show apps with status `ACTIVE` or `CREATING`
   - Exclude apps with status `DELETING`, `FAILED`, or `DELETED`

3. **Rank results:**
   - Apps with `AccountDefaultStatus=Enabled` appear first (account-wide default)
   - Then sort by most recently modified

4. **Present to user:**
   - Show: name, ARN, status, MLflow version, creation time
   - If exactly one ACTIVE app: suggest it directly — "You have one MLflow app: {name}. Use this one?"
   - If multiple ACTIVE apps: present a numbered list, ask user to choose
   - If zero apps found: inform user — "No MLflow apps found in {region}. Would you like me to create one?"

## Edge Cases

- **App in CREATING status:** Inform user it's still provisioning. Offer to wait (poll with `aws-mcp` `sagemaker:DescribeMlflowApp` until ACTIVE) or pick another app.
- **All apps are FAILED:** Suggest creating a new one rather than troubleshooting failed apps.
- **Wrong region:** If user expected to find an app, ask if they want to check a different region before offering to create.
