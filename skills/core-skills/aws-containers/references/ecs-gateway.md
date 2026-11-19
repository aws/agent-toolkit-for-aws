# Amazon ECS Gateway

Amazon ECS Gateway provides managed HTTP/HTTPS ingress that many ECS services share. A platform team creates a gateway, sets its ingress configuration (scheme, subnets, security group, AWS WAF web ACL, access logs), and associates it with one or more clusters. An application team connects a service by adding a gateway connector that names a container port. ECS then creates and manages the Application Load Balancers, listeners, security groups, certificates, target groups, and a generated HTTPS hostname for each service. The service must use the `awsvpc` network mode.

Use ECS Gateway when several services need HTTP/HTTPS ingress with shared settings. Do not build a separate load balancer, target group, and security group for each service when a gateway fits. Use ECS Express Mode when a team wants to deploy a web app or API on Fargate from a container image and let ECS choose the ingress, scaling, and networking defaults. Express Mode uses its own gateways, and an Express Mode service cannot use a gateway that you create. Attach your own Network Load Balancer for TCP or UDP traffic. Attach your own Application Load Balancer when you need to manage its listeners and rules yourself, because ECS does not repair changes made outside it to gateway-managed resources.

## Security considerations

Shared ingress means one gateway setting affects every connected service. Recommend these defaults and confirm the details in the documentation:

- A service that must never be reachable from the internet MUST set the gateway connector access type filter to `PRIVATE`. Without the filter, an internet-facing gateway associated with the cluster later exposes the service on its next deployment.
- Keep the default HTTPS listener on an internet-facing gateway. Do not switch it to HTTP.
- Associate an AWS WAF web ACL with an internet-facing gateway, and enable access logs to an Amazon S3 bucket that you own. Access logs can contain sensitive request metadata, so encrypt the bucket at rest with Amazon S3-managed keys (SSE-S3). Load balancer access logs do not support SSE-KMS.
- To restrict which clients reach the load balancers, supply an inbound security group that allows only the required sources. Do not allow `0.0.0.0/0` unless the service is meant to be public.
- Set security response headers (`Strict-Transport-Security`, `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`) in the application. The gateway has no header settings, and ECS does not repair changes made outside it to the load balancers it manages.
- Scope `iam:PassRole` to the gateway infrastructure role only.

## Documentation

Before advising or acting, the agent MUST read and cite the [Amazon ECS Gateway documentation](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/gateway-overview.html) at response time and answer from its published content. For setup, read [Create and manage a gateway](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/gateway-managing.html). To connect a service, read [Connect services to a gateway](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/gateway-connect-service.html). For failures, read [Troubleshoot Amazon ECS Gateway](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/gateway-troubleshooting.html). Do not copy prerequisites, API parameters, or procedures into this reference.
