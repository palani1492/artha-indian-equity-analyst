# AWS infrastructure

This stack deploys the Sentellent analyst as two independently scalable ECS
Fargate services behind one Application Load Balancer. `/api/*`, `/health`,
`/docs*`, and `/openapi.json` route to FastAPI; all other paths route to the
frontend. PostgreSQL 16 runs in isolated subnets on RDS and stores pgvector data.

The default is intentionally challenge-sized: one task per service, a
`db.t4g.micro`, 20 GiB of encrypted gp3 storage, 14-day logs, and no NAT
gateway. ECS tasks use public subnets for outbound-only internet access while
security groups allow inbound traffic exclusively from the ALB. Set
`enable_nat_gateway = true` to move tasks to private application subnets.

## Resources

- A two-AZ VPC with public, private application, and isolated database subnets
- Public ALB with same-origin path routing and optional ACM TLS
- Separate standard Next.js standalone and FastAPI ECR images with push scanning/lifecycle rules
- ECS Fargate cluster, services, task definitions, health checks, rollback, and CPU autoscaling
- Encrypted RDS PostgreSQL 16 with an AWS-managed master credential secret
- A separate Secrets Manager container for OAuth, session, and optional OpenAI credentials
- CloudWatch log groups, Container Insights, and basic ALB/database alarms
- Regional AWS WAF rate limiting on the Google OAuth callback
- EventBridge Scheduler invoking the idempotent ingestion CLI as a one-off ECS task
- Least-privilege runtime, execution, scheduler, and GitHub OIDC roles with a mandatory runtime permissions boundary
- S3 remote state with versioning, encryption, public-access blocking, and native lock files

## Prerequisites

- Terraform 1.7 or newer (CI pins 1.10.5)
- An AWS account and credentials for the one-time bootstrap
- Docker and the AWS CLI for manual deployments
- A GitHub repository and GitHub production environment
- Optional but strongly recommended: a domain and an ACM certificate in the deployment region

Google OAuth web callbacks require HTTPS outside localhost. Pass an ACM
certificate ARN, set `public_base_url`, and map that DNS name to the ALB before
configuring the OAuth client. Add `harisankar@sentellent.com` and
`naga@sentellent.com` as
Google OAuth test users. Update `GOOGLE_REDIRECT_URI` through
`backend_environment` if the final callback differs from the default
`/api/v1/auth/google/callback`.

## One-time bootstrap

The state bucket and the role that GitHub assumes cannot create themselves from
the main remote state. Bootstrap them once using trusted local AWS credentials:

```bash
cp infra/bootstrap/terraform.tfvars.example infra/bootstrap/terraform.tfvars
terraform -chdir=infra/bootstrap init
terraform -chdir=infra/bootstrap apply
terraform -chdir=infra/bootstrap output
```

If the AWS account already has the GitHub Actions OIDC provider, set
`create_github_oidc_provider = false` and pass its ARN. The trust policy accepts
only the configured repository's `production` environment, with the AWS STS
audience. Protect that GitHub environment so deployments are allowed only from
the `main` branch; environment-based jobs use an environment OIDC subject rather
than a branch-ref subject.

Create these GitHub repository variables from the bootstrap outputs:

| Variable | Value |
| --- | --- |
| `AWS_REGION` | Region used by bootstrap, normally `ap-south-1` |
| `AWS_ROLE_ARN` | `github_actions_role_arn` output |
| `TF_STATE_BUCKET` | `state_bucket_name` output |
| `TF_STATE_KEY` | `state_key` output, normally `production/terraform.tfstate` |
| `PROJECT_NAME` | `sentellent`, or the bootstrap project name |
| `ACM_CERTIFICATE_ARN` | Required regional ACM certificate ARN for the public domain |
| `PUBLIC_BASE_URL` | Required canonical origin such as `https://stocks.example.com` |

Create these secrets in the GitHub `production` environment:

| Secret | Required | Notes |
| --- | --- | --- |
| `SESSION_SECRET` | yes | At least 32 random characters; generate with `openssl rand -hex 32` |
| `GOOGLE_CLIENT_ID` | for Google auth | OAuth web client ID |
| `GOOGLE_CLIENT_SECRET` | for Google auth | OAuth web client secret |
| `OPENAI_API_KEY` | no | Leave unset for deterministic demo/local AI mode |

The deployment workflow first creates only the ECR repositories and empty
application secret, writes secret values directly through the Secrets Manager
API, and only then creates ECS. Application secret values therefore never enter
Terraform configuration, plans, or state. RDS generates and manages its own
password in Secrets Manager.

## Main stack configuration

Copy `terraform.tfvars.example` if you need values beyond CI defaults. Initialize
the same remote state locally with values from bootstrap:

```bash
terraform -chdir=infra init \
  -backend-config="bucket=YOUR_STATE_BUCKET" \
  -backend-config="key=production/terraform.tfstate" \
  -backend-config="region=ap-south-1" \
  -backend-config="encrypt=true" \
  -backend-config="use_lockfile=true"
terraform -chdir=infra plan
```

Do not commit `terraform.tfvars`, plan files, local state, or runtime secrets.
The backend receives `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USERNAME`, and
`DB_PASSWORD`; it constructs `DATABASE_URL` internally. Local Compose supplies
`DATABASE_URL` directly.

Important production variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `certificate_arn` | required | Enables HTTPS on the ALB and redirects HTTP |
| `public_base_url` | required | Canonical HTTPS origin mapped to the ALB and used for OAuth |
| `enable_nat_gateway` | `false` | Places ECS tasks in private subnets; adds a fixed NAT charge |
| `database_deletion_protection` | `false` | Turn on after the first successful production deployment |
| `image_tag` | `latest` | CI always overrides with the immutable commit SHA |
| `ingestion_schedule_expression` | `rate(6 hours)` | Scheduled refresh cadence |
| `ingestion_schedule_enabled` | `true` | Enables or pauses refresh jobs |
| `ingestion_command` | `-m app.jobs.ingest --all-followed` | Scheduled container command (distroless Python entrypoint) |
| `oauth_callback_rate_limit` | `100` | Per-IP OAuth callback limit in each five-minute WAF window |
| `backend_environment` | `{}` | Extra non-secret backend environment settings |

The production locals set `MARKET_DATA_PROVIDER=live` and `AI_PROVIDER=local`.
Live mode uses yfinance for quotes/fundamentals and the configured, rate-limited
RSS feeds for news; the deterministic provider is reserved for local evaluation.

Never put secret values in `backend_environment` or `.tfvars`; use the existing
Secrets Manager workflow. Keep AWS budgets/alerts enabled because ALB, WAF,
Fargate, RDS, public IPv4 addresses, NAT (when enabled), and data transfer are
billable.

## CI/CD order

Pull requests and non-main pushes run frontend lint/test/build, a high-severity
production `npm audit` gate, backend Ruff/mypy/pytest with an 80% coverage gate,
`pip-audit`, Playwright critical-flow tests, Terraform format/validation, and
both Linux/amd64 container builds. No workflow automatically rewrites dependency
versions. A main-branch push then:

1. Assumes the scoped AWS role with GitHub OIDC (no long-lived AWS keys).
2. Creates ECR/secret prerequisites and seeds Secrets Manager.
3. Builds and pushes commit-SHA and convenience `latest` image tags.
4. Fails when ECR reports critical image findings.
5. Registers the new backend task revision without updating the live service.
6. Runs `alembic upgrade head` on that revision and checks its exit code.
7. Saves and applies a Terraform plan, then waits for both services to stabilize.
8. Smoke-tests frontend, liveness, and database readiness endpoints.

ECS deployment circuit breakers automatically roll back tasks that cannot
become healthy. Images are addressed by commit SHA, so redeploying a previous
revision is deterministic.

## Local stack

Create an untracked `.env` with `POSTGRES_PASSWORD` and a 32+ character
`SESSION_SECRET`. OAuth and OpenAI values are optional in demo mode:

```bash
docker compose up --build
docker compose exec backend alembic upgrade head
```

The frontend is at `http://localhost:3000`, API at
`http://localhost:8000`, and PostgreSQL at `localhost:5432`.

## Operational checks

```bash
terraform -chdir=infra output application_url
aws ecs list-tasks --cluster sentellent-production --service-name backend
aws logs tail /ecs/sentellent-production/backend --follow
```

For submission evidence, capture the healthy ECS services and targets, private
RDS instance, populated Secrets Manager resources with values hidden, ECR image
scan results, EventBridge schedule, and the passing GitHub deployment workflow.
