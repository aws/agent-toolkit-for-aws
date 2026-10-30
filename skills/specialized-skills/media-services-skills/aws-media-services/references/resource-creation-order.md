# Resource Creation Order

Not every workflow uses all components. Skip services that aren't needed, but
respect these dependency rules — a resource must exist before anything that
references it.

## Live dependency chain

```
VPC / Subnets / Security Groups
  → IAM Role (with correct trust policy)
  → MediaPackage v2: Channel Group → Channel → Origin Endpoint(s)
  → MediaConnect: Flow (needs IAM role)
  → MediaLive: Input (needs VPC, subnets, security groups)
  → MediaConnect: Output (needs flow + MediaLive input endpoint IPs)
  → MediaLive: Channel (needs input ID + MediaPackage ingest URL)
  → MediaTailor: Playback config (needs TWO URLs: the content origin, MediaPackage here or any
    other public HLS/DASH origin, AND the ad decision server URL. No ADS URL means no ads)
  → CloudFront: Distribution (needs MediaTailor or MediaPackage endpoint URL)
```

## VOD dependency chain

```
CloudFront: Distribution (create first — propagation takes time)
  → S3 Buckets (source + destination; set as CloudFront origin with OAC)
  → IAM Role (trusts mediaconvert.amazonaws.com, S3 permissions)
  → MediaConvert: Job Queue (optional, default exists)
  → MediaConvert: Job Template (optional but recommended)
  → MediaConvert: Job (needs source S3 path, output S3 path, IAM role)
  → MediaPackage v2 VOD: Asset (if using MP v2 for VOD packaging)
```

## Live-to-VOD addition

```
Live chain above
  + MediaLive Archive output group → S3
    OR MediaPackage v2 Harvest Job → S3
  → S3 recording feeds MediaConvert job
  → Then follows VOD chain above
```

## Common flow patterns

| Pattern | Services |
|---------|----------|
| Full live chain | MediaConnect → MediaLive → MediaPackage → MediaTailor → CloudFront |
| Live, no transport | MediaLive (direct input) → MediaPackage → CloudFront |
| Live, no ad insertion | MediaConnect → MediaLive → MediaPackage → CloudFront |
| Live encode only | MediaConnect → MediaLive → S3/HLS output |
| Live repackage only | MediaPackage (existing ingest) → CloudFront |
| VOD transcode | S3 → MediaConvert → S3 → CloudFront |
| VOD with packaging | S3 → MediaConvert → MediaPackage v2 VOD → CloudFront |
| Live-to-VOD | Live chain + archive/harvest → MediaConvert → S3/CloudFront |
