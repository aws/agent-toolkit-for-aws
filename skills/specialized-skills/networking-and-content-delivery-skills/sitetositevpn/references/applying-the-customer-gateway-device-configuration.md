# Applying the Customer Gateway Device Configuration

## Overview

Domain expertise for configuring the on-premises customer gateway (CGW) device after an AWS
Site-to-Site VPN connection is created, so the tunnels come up. Covers downloading the AWS-provided
sample configuration file, choosing the recommended sample over the compatibility sample, treating
the sample as a starting point rather than a finished config, the IAM permissions the download
screen needs, configuring both tunnels, and handling an unlisted device.

This reference educates the customer on what to configure on their own device; it does not hand them
a ready-to-use configuration, because the right values depend on the device and security
requirements the agent cannot see. The configuration is applied on the customer's device, not on the
AWS side. Assumes the connection already exists (the creating-a-site-to-site-vpn-connection
reference).

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. Pass `--region {region}` matching the connection.

## Table of Contents

- Overview
- Workflow
- Educate, do not prescribe
- Recommended versus compatibility sample
- IAM permissions for the download screen
- Configure both tunnels
- Unlisted device
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To get the device configured, download the matching sample file, review and adapt it, and apply it
to both tunnels on the on-premises device. See the Procedure section below.

The procedure covers:

- Confirming the IAM permissions the download screen needs
- Downloading the sample for the device vendor, platform, software version, and IKE version
- Choosing the recommended sample where AWS offers one
- Reviewing and adapting the sample, then applying both tunnels on the device

## Educate, do not prescribe

The configuration this workflow produces is applied on the customer's on-premises device, not on the
AWS side. The skill's job is to explain what to configure, not to hand the customer a finished config
to paste in, because the right values depend on the customer's device and security requirements.

**Constraints:**

- You MUST explain the settings the device needs and offer the AWS sample as a starting point the customer reviews and adapts
- You MUST NOT present a single ready-to-use configuration as correct for the customer's device
- You MUST state that the configuration goes on the customer's device, not the AWS side

## Recommended versus compatibility sample

For many devices AWS offers two sample types: a compatibility sample and a recommended sample that
uses stronger settings. The sample specifies only minimum requirements (such as AES128, SHA1, and
Diffie-Hellman group 2 in most Regions), so applying it as-is can leave the customer on the weakest
acceptable settings.

**Constraints:**

- You MUST prefer the recommended sample where AWS offers one
- You MUST flag the sample as a starting point and prompt the customer to adjust algorithms,
  Diffie-Hellman groups, certificates, and IPv6 before applying it
- You MUST set strong tunnel options (AES-256, SHA-256 or higher, Diffie-Hellman group 14 or higher) rather than the AES-128 / SHA-1 / DH group 2 minimums

## IAM permissions for the download screen

Loading the download configuration screen requires the IAM permissions
`GetVpnConnectionDeviceTypes` and `GetVpnConnectionDeviceSampleConfiguration`. Without them the
screen does not populate, with no obvious explanation that a missing permission is the cause.

**Constraints:**

- You MUST check for `GetVpnConnectionDeviceTypes` and `GetVpnConnectionDeviceSampleConfiguration` if the download screen is empty
- You SHOULD name the missing permission so the customer is not stuck staring at a blank screen

## Configure both tunnels

The configuration covers both tunnels. Applying only the first leaves the connection without the
redundancy AWS provides, so it drops during routine tunnel maintenance. Customers stop after the
first tunnel because the connection appears to work.

**Constraints:**

- You MUST confirm both tunnels are configured on the device, not just one
- You SHOULD explain that the second tunnel is what keeps the connection up during tunnel maintenance

## Unlisted device

When the customer's exact device is not in the vendor list they do not know how to proceed, and the
supported algorithms and IKE versions vary by device.

**Constraints:**

- You MUST point the customer to the Generic configuration option for an unlisted device
- You MUST strongly recommend IKEv2 over IKEv1 if the customer's device supports it; IKEv2 is simpler, more robust, and more secure (see [AWS best practices](https://docs.aws.amazon.com/vpn/latest/s2svpn/cgw-best-practice.html)). Only use IKEv1 when the device does not support IKEv2

## Troubleshooting

### Tunnels stay down after applying the sample
The sample is a starting point; algorithms or settings may not match the device's needs. Review and adapt it (Educate, do not prescribe).

### Download configuration screen is empty
Missing `GetVpnConnectionDeviceTypes` or `GetVpnConnectionDeviceSampleConfiguration`. Add the permissions (IAM permissions for the download screen).

### Connection drops during maintenance
Only one tunnel was configured. Configure both (Configure both tunnels).

### Device is not in the vendor list
Use the Generic configuration option and the correct IKE version (Unlisted device).

## Procedure

### Overview

This procedure confirms the download permissions, downloads the matching sample (preferring the
recommended type), guides the customer to review and adapt it, and confirms both tunnels are
configured, then surfaces the console link to verify tunnel status.

### Parameters

- **region** (required): The AWS Region of the connection.
- **vpn_connection_id** (required): The connection whose configuration to download.
- **device_vendor** (required): The on-premises device vendor, platform, and software version.
- **ike_version** (required): `ikev1` or `ikev2`, matching the device. Strongly recommend `ikev2` unless the device does not support it.
- **sample_type** (optional): `recommended` (preferred) or `compatibility`.

**Constraints for parameter acquisition:**

- You MUST ask for the device vendor, platform, software version, and IKE version upfront
- You SHOULD confirm whether the device is in the supported list or needs the Generic option

### Steps

#### 1. Confirm download permissions

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You SHOULD recommend ephemeral IAM role-based credentials (instance profile, SSO session, or assumed role) rather than long-lived IAM user access keys for running these commands
- You MUST confirm the caller has `GetVpnConnectionDeviceTypes` and `GetVpnConnectionDeviceSampleConfiguration`

#### 2. Resolve the device type ID

**Constraints:**

- You MUST resolve the vendor/platform/software version to a `{device_type_id}` first, since
  `get-vpn-connection-device-sample-configuration` takes the numeric ID, not a human-readable name.
  List the supported device types and match the customer's device (vendor, platform, software) to
  its `DeviceTypeId`:

  ```
  aws ec2 get-vpn-connection-device-types --region {region}
  # Find the entry whose Vendor/Platform/Software match the customer's device; use its DeviceTypeId
  ```

- You MUST use the Generic device type's ID when the customer's device is not in the returned list

#### 3. Download the sample configuration

**Constraints:**

- You MUST download the sample for the resolved device type ID and IKE version, preferring the recommended sample:

  ```
  aws ec2 get-vpn-connection-device-sample-configuration \
    --vpn-connection-id {vpn_connection_id} --vpn-connection-device-type-id {device_type_id} \
    --internet-key-exchange-version {ike_version} --sample-type recommended --region {region}
  ```

#### 4. Review and adapt

**Constraints:**

- You MUST present the sample as a starting point and prompt the customer to adjust algorithms, Diffie-Hellman groups, certificates, and IPv6
- You MUST NOT tell the customer to apply the sample unchanged as if it were correct for their device

#### 5. Apply both tunnels and confirm

**Constraints:**

- You MUST confirm the customer configures both tunnels on the device, not just one
- You MUST present the VPN connection console link, filling `{region}` and `{vpnConnectionId}` from
  the request, and tell the customer to open it and confirm both tunnels report UP:

  ```
  https://console.aws.amazon.com/vpc/home?region={region}#VpnConnectionDetails:VpnConnectionId={vpnConnectionId}
  ```

### Example

#### Example input

```json
{
  "region": "us-east-1",
  "vpn_connection_id": "vpn-0abc1234def567890",
  "device_vendor": "Cisco ASA 9.x",
  "ike_version": "ikev2",
  "sample_type": "recommended"
}
```

#### Example output

```
Confirmed download permissions. Downloaded the recommended IKEv2 sample for Cisco ASA 9.x.
Flagged it as a starting point: adjust algorithms, DH group, certificates, and IPv6 before applying.
Both tunnels configured on the device. Open the connection and confirm both tunnels report UP:
https://console.aws.amazon.com/vpc/home?region=us-east-1#VpnConnectionDetails:VpnConnectionId=vpn-0abc1234def567890
```

### Troubleshooting

#### Tunnels down after applying
The sample needs adapting to the device. Review the algorithms and settings (Step 4).

#### Download screen empty
Missing IAM permissions. Add `GetVpnConnectionDeviceTypes` and `GetVpnConnectionDeviceSampleConfiguration` (Step 1).

#### Connection drops during maintenance
Only one tunnel configured. Configure both (Step 5).

## Security Considerations

The device configuration carries the authentication secret and the encryption settings the tunnels
negotiate, so it is the most security-sensitive artifact the customer handles.

**Constraints:**

- You MUST set strong tunnel options (AES-256, SHA-256 or higher, Diffie-Hellman group 14 or higher) rather than the AES-128 / SHA-1 / DH group 2 minimums
- You MUST treat tunnel pre-shared keys (PSKs) as secrets: never pass them on the command line or store them in plaintext, store them in AWS Secrets Manager, and rotate them periodically; where the device supports it, recommend certificate-based authentication with AWS Private Certificate Authority instead of a static PSK
- You SHOULD remind the customer that the downloaded sample contains live tunnel secrets and should
  be deleted from any temporary or download location once applied
- You SHOULD enable Amazon CloudWatch tunnel-state alarms and Site-to-Site VPN logs, and confirm AWS CloudTrail is enabled so the API calls that create, modify, or delete the connection are audited (see the monitoring-and-troubleshooting-tunnels reference). You MUST enable encryption at rest on every log destination — KMS on the CloudWatch Logs log group holding the VPN/tunnel logs and SSE-S3 or SSE-KMS on the S3 bucket holding the CloudTrail logs — since these logs can carry tunnel and connection detail

## Additional Resources

- [Get started with AWS Site-to-Site VPN (AWS Site-to-Site VPN User Guide)](https://docs.aws.amazon.com/vpn/latest/s2svpn/SetUpVPNConnections.html)
- [Static and dynamic configuration files for an AWS Site-to-Site VPN customer gateway device (AWS Site-to-Site VPN User Guide)](https://docs.aws.amazon.com/vpn/latest/s2svpn/example-configuration-files.html)
- [AWS Site-to-Site VPN customer gateway devices (AWS Site-to-Site VPN User Guide)](https://docs.aws.amazon.com/vpn/latest/s2svpn/your-cgw.html)
