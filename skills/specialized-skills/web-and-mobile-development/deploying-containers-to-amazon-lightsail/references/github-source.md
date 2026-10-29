# Deploy from a GitHub repository

Lightsail does **not** build from a git repository. The build happens on your machine; from there this is exactly
the local-image path. The repo must contain a Dockerfile.

## Steps

1. Clone the repo and confirm it has a Dockerfile:

   ```bash
   git clone REPO_URL && cd REPO
   ```

   If there is no Dockerfile, the app must be containerized first — this path does not apply until it is.
2. Build for `linux/amd64`:

   ```bash
   docker build --platform linux/amd64 -t my-app .
   ```

3. From here, follow the local-image path — push the built image into the service registry, then deploy. See
   [local-image.md](references/local-image.md) (steps 2–3) and [deployment.md](references/deployment.md).

## Notes

- The container service does not build from the repo and does not auto-redeploy on `git push`. Automatic
  redeploy-on-push is a separate CI/CD concern and is not part of this path.
