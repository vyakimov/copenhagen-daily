# Copenhagen Daily on AWS: the delivery as built

Status: live since 29 September 2026 at [copenhagen-daily.net](https://copenhagen-daily.net); one
step remaining, Terraform. Written for the owner, in the same spirit as the
[block 2 architecture](editorial-architecture.md). The project's architecture did not change for
this: three blocks, one schedule, file contracts between them, SQLite behind each. The Mac Studio is
the newsroom and runs all three blocks; AWS is delivery only, the place the finished static site is
served from. Every service below is one the owner can explain, and the design stays small and cheap.

## The map: which service for which job

| Job in the project | Service | As built |
|---|---|---|
| Own the account without the root user | **IAM Identity Center** | One admin user in Identity Center. People sign in through it; the AWS CLI profile `copenhagen-daily` is an SSO profile for a person at the keyboard and is never used by a job. |
| Serve the web edition and the device PNG | **S3 + CloudFront** | A private bucket, `copenhagen-daily-live`, behind CloudFront distribution `E67FD57M9R899` on the free plan. The bucket holds block 3's `live/` directory as it is; CloudFront serves it over HTTPS with caching. |
| Domain and certificate | **Route 53 + ACM** | `copenhagen-daily.net` is registered in Route 53, with alias records for the bare name and `www` pointing at the distribution. The certificate is from ACM and renews itself. |
| Tidy URLs and the unlisted posture | **CloudFront Functions** | Two functions. Viewer request: redirect `www` to the bare name and rewrite a directory path to its `index.html`, so block 3's permalinks work unchanged. Viewer response: add `X-Robots-Tag: noindex, nofollow` to every object, so files that carry no HTML meta tag are unlisted too. |
| Let the scheduled job deliver without a browser | **IAM user with an inline policy** | `copenhagen-daily-deliver`, whose policy allows `ListBucket` on the bucket, `PutObject` and `DeleteObject` on its objects, and `CreateInvalidation` on the distribution, and nothing else. Its access key is the CLI profile named in `editorial/config/desk.yaml` under `delivery.profile`, so the launchd job can run `aws` with no person present. |
| Get the paper onto the site | **The desk's `deliver` phase** | After each activated publish the desk runs `aws s3 sync --delete --exact-timestamps` of block 3's `live/` directory to the bucket, then a `/*` invalidation on the distribution (`editorial/src/news_editorial/deliver.py`). `edit_news.sh deliver` does the same by hand. With no bucket configured the phase is skipped. |
| Know the paper is really up | **`verify-live` at 06:00** | The verify job fetches `latest.json`, the front page, and the edition's manifest from `delivery.site_url` and compares them byte for byte with the newsroom's live tree, then checks the stylesheet and the robots header (`verify.py`). Its verdict is posted every morning, good or bad; `--fix` delivers again when that is the whole remedy. |
| Keep the paper out of search while licensing is unresolved | **noindex, three ways** | Every page carries a `noindex` meta tag, the release root has a `robots.txt` that disallows everything, and the response function adds the header. The paper is public and unlisted: anyone with the link can read it, nobody finds it by searching. |

The bucket is private; only CloudFront reads it. Nothing in AWS runs code of the project's own.
Collection, the editorial sessions, the build, and the publish all happen on the Mac under launchd
(`editorial/OPERATIONS.md`), and the only thing that crosses to AWS is a directory of finished files.

## What was not built, and what was chosen instead

The first plan for this page had three pieces that were dropped once the desk existed as a Claude
Code session on the owner's machine.

- **An EC2 instance running the blocks under cron.** The Mac Studio runs them under launchd instead,
  because the editor session needs the owner's Claude Code subscription and the pinned Chromium, and
  a machine that is already on is cheaper and simpler than one to patch.
- **GitHub Actions deploying through OIDC.** The desk delivers from the newsroom under a scoped IAM
  user instead, because delivery is a step of the morning run and not of a code push.
- **A shared-secret edge function to keep the site private.** The site is public but unlisted
  instead, with `noindex` in the page, in `robots.txt`, and in a response header, because a secret in a
  cookie would have kept out the kitchen screen and the owner's phone as surely as everyone else.

Still true and still worth saying: no managed database, since SQLite behind each block is the right
size and lives on the Mac; no Lambda, since nothing here is event-driven; no Kubernetes and no
containers; no load balancer and no VPC design, since CloudFront talks to S3 and nothing else listens.

## What remains

**Terraform for what was clicked.** The bucket and its policy, the distribution and its two
functions, the certificate, the hosted zone's records, and the IAM user with its inline policy exist
because they were created in the console. Declaring them in Terraform, importing the live resources
into its state, and confirming that a plan shows no drift is the step that makes the delivery
reproducible. It is listed in the [roadmap](roadmap.md); the staging paper designed there would be a
second instance of the same module, which is the practical reason to do it before that.

## The sentence for the interview

"A three-stage news pipeline with SQLite state, run on a schedule on one machine, that publishes an
immutable static site through S3 and CloudFront with Route 53 and ACM in front, delivered by a
least-privilege IAM user, checked from outside every morning, and kept unlisted with two CloudFront
Functions. I chose against a server in the cloud, a CI deploy, and a managed database, and I can tell
you why for each."
