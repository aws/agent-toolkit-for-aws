# Networking — Enterprise Hybrid (TGW + VPN / Direct Connect)

Production-ready pattern for connecting on-prem data centers, corporate offices, and remote sites to ODB@AWS via AWS Transit Gateway combined with Site-to-Site VPN or AWS Direct Connect.

## Architecture

```
Corporate Office ── VPN ──┐
                          │
Data Center ── DX ────────┤── TGW ── Transit VPC ── ODB Peering ── ODB Network
                          │           (ODB peering + R53R endpoints)
Branch Office ── VPN ─────┘
App VPCs ─────────────────┘
```

## Components

- **TGW** — central routing hub. VpnEcmpSupport + DnsSupport enabled.
- **Transit VPC** — holds the ODB peering, the Route 53 Resolver outbound endpoint, and (for on-prem DNS) a Resolver inbound endpoint.
- **Site-to-Site VPN (attached to TGW)** — IPsec over public internet; dual tunnels per connection; BGP.
- **Direct Connect (via DX Gateway + TGW association)** — dedicated private connection; low latency; optional MACsec encryption on DX 10 Gbps.

## TGW + Site-to-Site VPN

### 1. Create Transit Gateway

```bash
aws ec2 create-transit-gateway \
  --description "ODB enterprise hybrid" \
  --options "AmazonSideAsn=64512,AutoAcceptSharedAttachments=enable,DefaultRouteTableAssociation=enable,DefaultRouteTablePropagation=enable,VpnEcmpSupport=enable,DnsSupport=enable" \
  --region us-east-1
```

### 2. Customer gateway + VPN attached to TGW

```bash
aws ec2 create-customer-gateway \
  --type ipsec.1 --public-ip 203.0.113.10 --bgp-asn 65000 \
  --region us-east-1

aws ec2 create-vpn-connection \
  --type ipsec.1 \
  --customer-gateway-id cgw-0abc \
  --transit-gateway-id tgw-0abc \
  --options "TunnelInsideIpVersion=ipv4,StaticRoutesOnly=false" \
  --region us-east-1
```

`StaticRoutesOnly=false` means BGP — on-prem routes propagate automatically.

### 3. Attach the transit VPC and create ODB peering

Follow **networking-odb-peering.md** (loaded reference) from the transit VPC.

### 4. TGW route table

```bash
aws ec2 create-transit-gateway-route \
  --transit-gateway-route-table-id tgw-rtb-0abc \
  --destination-cidr-block 10.20.0.0/24 \
  --transit-gateway-attachment-id tgw-attach-transit-vpc
```

BGP-advertised on-prem CIDRs propagate automatically.

### 5. DNS — on-prem clients

For VPC-resident clients, follow **networking-dns-resolver.md** (loaded reference).

For on-prem clients, add a Route 53 Resolver **inbound** endpoint in the transit VPC:

```bash
aws route53resolver create-resolver-endpoint \
  --name odb-inbound-for-onprem \
  --direction INBOUND \
  --security-group-ids sg-0abc \
  --ip-addresses SubnetId=subnet-transit-a SubnetId=subnet-transit-b \
  --region us-east-1
```

Configure on-prem DNS to forward `oraclevcn.com` to the inbound endpoint IPs:

- **Windows DNS Server:**
  ```powershell
  Add-DnsServerConditionalForwarderZone -Name "oraclevcn.com" -MasterServers 10.30.0.10,10.30.0.11
  ```
- **BIND:**
  ```
  zone "oraclevcn.com" { type forward; forward only; forwarders { 10.30.0.10; 10.30.0.11; }; };
  ```
- **Infoblox:** forward zone `oraclevcn.com` → inbound endpoint IPs.

## TGW + Direct Connect

### 1. DX Gateway + association

```bash
aws directconnect create-direct-connect-gateway \
  --direct-connect-gateway-name odb-dx-gw --amazon-side-asn 64513

aws directconnect create-direct-connect-gateway-association \
  --direct-connect-gateway-id <dxgw-id> \
  --gateway-id tgw-0abc \
  --add-allowed-prefixes "cidr=10.20.0.0/24" "cidr=10.10.0.0/16"
```

`allowed-prefixes` controls which routes are advertised to on-prem via BGP.

### 2. DX transit virtual interface

```bash
aws directconnect create-transit-virtual-interface \
  --connection-id <dxcon-id> \
  --new-transit-virtual-interface '{
    "virtualInterfaceName": "odb-transit-vif",
    "vlan": 100,
    "asn": 65000,
    "directConnectGatewayId": "<dxgw-id>",
    "addressFamily": "ipv4"
  }'
```

### 3. Remaining steps

Same as the VPN path from step 3 onward — transit VPC, ODB peering, TGW routes, DNS forwarding.

## High Availability

- VPN: 2 tunnels per connection (AWS default); use 2 VPN connections for maximum HA; enable `VpnEcmpSupport` on TGW.
- DX: dual DX connections to different locations; DX + VPN backup (BGP AS path prepending) is a common pattern.
- TGW is inherently multi-AZ. ODB peering is single-AZ (the ODB network maps to one AZ ID).

## Monitoring

```bash
aws ec2 describe-vpn-connections --vpn-connection-ids <vpn-id> \
  --query 'VpnConnections[].VgwTelemetry'

aws directconnect describe-virtual-interfaces \
  --query 'virtualInterfaces[].{Name:virtualInterfaceName,State:virtualInterfaceState,BGP:bgpPeers[0].bgpStatus}'
```

CloudWatch metrics to watch: `TunnelState` (VPN, 1=UP/0=DOWN), `BytesIn` / `BytesOut` per TGW attachment, `ConnectionState` (DX).

## Common Mistakes

| Mistake | Symptom | Fix |
|---|---|---|
| VPN attached to VGW instead of TGW | Only one VPC reaches on-prem | Recreate VPN attached to TGW |
| DX allowed-prefixes missing ODB CIDR | On-prem cannot route to ODB | Update `allowed-prefixes` |
| On-prem DNS not forwarding `oraclevcn.com` | NXDOMAIN from on-prem | Conditional forwarder → resolver inbound endpoint |
| Single VPN tunnel | Outage on maintenance | Use 2 tunnels + ECMP |
| Firewall blocks 1521/2484 on-prem | Timeout from on-prem | Open outbound rules |
| MTU fragmentation over VPN | Slow queries | Set TCP MSS clamping to 1379 on the VPN device |

## Security

- TCPS (wallet) provides end-to-end encryption client-to-database, independent of VPN/DX encryption. Use TCPS as defense in depth even over encrypted paths.
- IPsec on VPN (AES-256, SHA-256 by default). DX itself is unencrypted — use MACsec (DX 10 Gbps) or IPsec-over-DX if encryption is required.
