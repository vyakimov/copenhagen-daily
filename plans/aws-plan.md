# Putting Copenhagen Daily on AWS: a plan for the person doing it

Status: build plan, 14 September 2026. Broad strokes only, in the same spirit as the
[block 2 build plan](news-editorial-build-plan.md): written for the owner, who has no cloud experience
yet and wants to change that in a way an interviewer will recognise. The project's architecture does
not change. Three blocks, one schedule, file contracts between them, SQLite behind each. AWS is where
that runs and how it is delivered, not a reason to redesign it. Every choice below is made so that the
system stays small and cheap, and so that each service you touch is one you can explain.

## The map: which service for which job

| Job in the project | Service | Why this one |
|---|---|---|
| Serve the web edition and the device PNG | **S3 + CloudFront** | The publisher already produces an immutable directory of static files. S3 holds it, CloudFront serves it over HTTPS with caching. This is the canonical static-site pattern and the first thing to build. |
| Domain and certificate | **Route 53 + ACM** | A real hostname for the paper and the device URL. ACM certificates are free and renew themselves. |
| Keep the paper private while licensing is unresolved | **CloudFront Functions** (or signed URLs) | The plans say no public posting is authorised. A small edge function checking a shared secret in a cookie or header keeps the site reachable by you and the device only. Cheaper and simpler than WAF for one reader. |
| Run the three blocks on a schedule | **EC2 (one small ARM instance) with cron** | The honest fit for "three CLIs, one machine, SQLite". You learn instances, security groups, IAM instance roles, and SSM Session Manager for access without SSH keys. Lambda is the wrong shape here: SQLite needs a disk that persists, and 5-minute polling of 130 feeds is a long-running process, not a function. |
| Later: the same, containerised | **ECS on Fargate, scheduled by EventBridge, with EFS for state** | The second-level version once EC2 is understood. Containers are what interviewers expect; scheduled Fargate tasks are how a batch pipeline runs without a server to patch. EFS gives SQLite a persistent disk; keep the one-writer rule and expect to say why NFS and SQLite need care. Optional. |
| Keep bundles, backups, and receipts safe | **S3 with lifecycle rules and Object Lock** | Block 1's backups and export bundles, block 3's published bundles. Object Lock makes "published editions are immutable" a property of the bucket rather than a promise in a README. Lifecycle rules move old raw payloads to cheaper storage. |
| The Anthropic API key and any other secret | **Systems Manager Parameter Store** (SecureString) | Secrets Manager is the enterprise answer; Parameter Store does the same for one key at no cost. The blocks read it at start through the instance role, so no key ever sits in a file. |
| Model calls from block 2 | **Amazon Bedrock** | Claude is available on Bedrock, and the Anthropic SDK has a Bedrock client, so block 2's provider interface can point at it with IAM credentials instead of an API key. Gives you Bedrock on the CV with a one-line change, and lets you compare cost and latency against the direct API. |
| Logs and alarms | **CloudWatch Logs, CloudWatch Alarms, SNS** | The blocks already write one JSON object per line to stderr. Ship that to CloudWatch, alarm on block 1's failure threshold and on a missed morning edition, and let SNS email you. Structured logs plus a metric filter is the whole observability story for a system this size. |
| Infrastructure as code | **Terraform** | CDK in Python would keep one language, but Terraform is the more transferable skill and the one most job adverts name. Everything above is declared in it; nothing is clicked into existence twice. |
| Deploy on push | **GitHub Actions with OIDC to AWS** | The workflow assumes an IAM role through OpenID Connect, so there are no long-lived AWS keys in GitHub. It runs the checks, syncs the publisher's release to S3, and invalidates CloudFront. This is the pattern interviewers ask about. |
| Cost control | **AWS Budgets** | Set a monthly alarm on day one. Everything above fits in a few dollars a month on a small instance; the things that surprise people are NAT gateways and idle load balancers, and this design needs neither. |

## What to leave out, and be ready to say why

- **No managed database.** Aurora or DynamoDB would mean rewriting every block's storage for no gain
  at this scale. SQLite on a persistent disk with backups to S3 is the right answer, and defending it is
  a better interview moment than having migrated away from it.
- **No Lambda for the pipeline.** Right for event-driven glue, wrong for a stateful poller. Use it, if
  at all, for one small thing: a nightly check that the latest edition is fresher than 24 hours.
- **No Kubernetes.** Fargate gives the container story without the operational weight.
- **No load balancer, no VPC design.** One instance in the default VPC with a security group that
  allows nothing inbound; access goes through SSM. CloudFront talks to S3, not to the instance.

## Build order

Each step is one thing to learn and one thing to show. Do them in sequence; each is small.

1. **Account hygiene.** IAM Identity Center for your own login, MFA, a budget alarm, and a Terraform
   state bucket. You learn: how not to use the root account.
2. **Static delivery.** S3 bucket, CloudFront distribution, the edge function for privacy, Route 53 and
   ACM. Upload one published release by hand and read the paper at a real URL. You learn: the static
   site pattern, caching, TLS.
3. **Terraform for step 2.** Recreate what you clicked as code, destroy it, apply it again. You learn:
   state, plan and apply, drift.
4. **The pipeline on EC2.** One ARM instance, an instance role that can read Parameter Store and write
   to the S3 buckets, cron running block 1 every five minutes and the edition each morning. Access via
   SSM only. You learn: roles versus keys, security groups, why the instance has no inbound ports.
5. **Bedrock for block 2.** Point the provider interface at Bedrock through the instance role and
   compare against the direct API. You learn: IAM-authenticated model access, regional availability.
6. **Logs and alarms.** CloudWatch agent shipping the structured logs, a metric filter on failures,
   two alarms, one SNS topic to your email. You learn: observability without a product.
7. **Deploy on push.** GitHub Actions assuming a role through OIDC, running the checks and publishing
   the release. You learn: keyless CI, least privilege for automation.
8. **Backups and immutability.** Block 1 backups to S3 on a schedule, Object Lock on the published
   bundle bucket, lifecycle rules for raw payloads. You learn: durability as configuration.
9. **Optional: containers.** Dockerfiles for the blocks, ECS on Fargate with scheduled tasks and EFS,
   run alongside EC2 until it proves itself, then retire the instance. You learn: what changes when the
   server is gone.

## The sentence for the interview

"A three-stage news pipeline with SQLite state, running on a single small instance with no inbound
ports, publishing an immutable static site through S3 and CloudFront, deployed from GitHub with OIDC,
all declared in Terraform, with model calls through Bedrock and alarms in CloudWatch. I chose against a
managed database, Lambda, and Kubernetes, and I can tell you why for each."
