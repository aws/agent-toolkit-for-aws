# Elastic Beanstalk - Supported Platforms

These rules apply after Elastic Beanstalk has been selected as the deployment
target by the deploy skill.

Detect the application's language and framework, then map to an EB platform branch.

## Platform Detection

| Signal in Codebase                              | EB Platform            | Notes                          |
| ----------------------------------------------- | ---------------------- | ------------------------------ |
| `requirements.txt`, `Pipfile`, `pyproject.toml` | Python on AL2023       | Django, Flask, FastAPI         |
| `package.json` (backend Node.js)                | Node.js on AL2023      | Express, NestJS, Fastify, Hono |
| `pom.xml`, `build.gradle`, `.jar`               | Corretto on AL2023     | Spring Boot, Quarkus           |
| `pom.xml`, `build.gradle`, `.war`               | Tomcat on AL2023       | WAR-based Java web apps        |
| `Gemfile`, `config.ru`                          | Ruby on AL2023         | Rails, Sinatra                 |
| `go.mod`                                        | Go on AL2023           | Any Go HTTP server             |
| `*.csproj`, `*.sln` (ASP.NET Core)              | .NET on AL2023         | ASP.NET Core on Linux          |
| `*.csproj`, `*.sln` (.NET Framework)            | .NET on Windows Server | IIS, .NET Framework 4.x        |
| `composer.json`                                 | PHP on AL2023          | Laravel, Symfony               |
| `Dockerfile`                                    | Docker on AL2023       | Any containerized app          |

## Platform Selection Rules

1. If `Dockerfile` exists AND a language runtime is also detected, ask the user for an explicit selection.
2. If multiple languages detected, ask the user for an explicit selection.
3. Always use Amazon Linux 2023 unless the app requires Windows (.NET Framework,
   IIS dependencies).
4. For Java apps: if `.war` file, deploy to Tomcat platform. If `.jar` with
   embedded server (Spring Boot), use Corretto platform.
5. Always use the latest supported runtime version unless the application
   specifies a version constraint (e.g., `engines` in `package.json`,
   `<TargetFramework>` in `.csproj`).

## Supported Deployment Artifacts

| Platform           | Accepted Input                                        |
| ------------------ | ----------------------------------------------------- |
| Language platforms | Source bundle (zip of source code)                    |
| .NET               | Published output (`dotnet publish` zip, not source)   |
| Java (.jar)        | Built artifact (fat jar or exploded directory)        |
| Docker             | Source bundle containing Dockerfile                   |
| Docker (pre-built) | Dockerfile with `FROM` referencing ECR/registry image |

.NET and Java platforms require pre-built artifacts. Run `dotnet publish` or
`mvn package`/`gradle build` before zipping. Other language platforms (Python,
Node.js, Ruby, Go, PHP) accept raw source and build on-instance.

## Worker Platform Considerations

Worker environments use the same platforms as web server environments. The
difference is the SQS daemon that delivers messages to the application over HTTP
on `localhost`. The application must expose an HTTP endpoint (default: `POST /`)
that processes each message.
