# Deploy a public registry image

The image already lives in a registry Lightsail can pull (Docker Hub, Amazon ECR Public), so there is no build and
no push — reference the image directly in the deployment. No `docker` or `lightsailctl` is needed for this path.

## Steps

1. Create the service and wait for `READY` (SKILL.md Workflow, step 1) — poll with:

   ```bash
   aws lightsail get-container-services --service-name NAME --region REGION
   ```

2. Deploy with `create-container-service-deployment`. The `image` is the public reference (e.g.
   `public.ecr.aws/nginx/nginx:latest` or `docker.io/library/nginx:latest`), and `publicEndpoint.containerPort` must
   be the port the app listens on **and** appear in that container's `ports`.

   ```bash
   aws lightsail create-container-service-deployment \
     --service-name NAME \
     --containers '{"web":{"image":"public.ecr.aws/nginx/nginx:latest","ports":{"80":"HTTP"}}}' \
     --public-endpoint '{"containerName":"web","containerPort":80,"healthCheck":{"path":"/"}}' \
     --region REGION
   ```

3. Poll the deployment to `ACTIVE` and verify the URL — see [deployment.md](references/deployment.md).

## Notes

- If the image is in a **private** registry (for example a private Amazon ECR repository), that is a different
  path — configure `privateRegistryAccess` on the service so Lightsail can pull it; it is not covered here.
