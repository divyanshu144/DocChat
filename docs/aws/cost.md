# Cost

**These are order-of-magnitude estimates, not quotes.** They use approximate on-demand list prices for a US region
recalled from memory, 730 hours per month, no discounts, light traffic, and exclude LLM provider charges and data transfer
beyond a few GB. Verify with the AWS Pricing Calculator for your region before committing. Nothing here has been billed.

## Monthly estimate by environment

| Component | Dev (`dev.tfvars.example`) | Prod-like (`prod.tfvars.example`) | Notes |
|---|---|---|---|
| Fargate API (1 vCPU / 2 GB) | ~$36 (1 task) | ~$72-215 (2-6 tasks) | ~$0.049/task-hour |
| Fargate worker (1 vCPU / 4 GB) | ~$43 (1 task) | ~$43-260 (1-6 tasks) | ~$0.058/task-hour; scales on queue depth |
| NAT gateway | ~$33 + data | ~$66 + data (one per AZ) | Often the largest surprise; $0.045/GB processed |
| Application load balancer | ~$18 | ~$25 | Plus LCUs |
| RDS PostgreSQL | ~$14 (t4g.micro, 20 GB) | ~$100-130 (t4g.medium, Multi-AZ) | Multi-AZ doubles the instance cost |
| Qdrant EC2 + EBS | ~$18 (t3.small, 20 GB) | ~$70 (t3.large, 100 GB) | Plus snapshot storage |
| Secrets Manager, KMS, Route 53 zone | ~$5 | ~$5 | 4 secrets, 2 keys, 1 private zone |
| CloudWatch (alarms, logs, Container Insights, flow logs) | ~$10-25 | ~$30-80 | Logs are the variable part |
| S3, SQS, ECR | <$5 | <$10 | Storage and requests are small |
| **Total** | **~$180-200** | **~$450-900** | Prod range is driven by task counts |

## Demo profile (`demo = true`) and the real cost of a short demo

For a short-lived environment, set `demo = true` in your tfvars (it is off by default). It changes only cost settings. The
network, encryption, IAM and secrets are exactly the same as the normal profile.

| Setting | Normal | Demo |
|---|---|---|
| Worker capacity | Fargate | **Fargate Spot** (roughly 70% cheaper; can be reclaimed, and the queue retries the job) |
| Worker minimum tasks | `worker_min_count` | **0**, scales out from zero |
| Scale-out alarm | 10 queued messages for 2 minutes | **1 queued message for 1 minute** |
| Ingest attempts | `ingest_max_attempts` (3) | at least **5**, because a Spot reclaim uses one attempt |
| Database | `db_instance_class`, `db_multi_az` | **`db.t4g.micro`, single AZ** |
| Log retention | `log_retention_days` | **7 days** |

Trade-off to expect: the first ingest after an idle period waits roughly 3 to 5 minutes (alarm evaluation, then pulling a
1.4 GB image and loading the embedding model). The chat API is unaffected. Set `budget_email` (and `budget_limit_usd`) to get
AWS Budget alerts at 50% and 80% of actual spend and 100% of the forecast; the budget is created whenever an email is given,
demo or not.

**Estimate only** (same assumptions as above, US region list prices from memory; verify before relying on them):

| Item | About per month | About per day |
|---|---|---|
| API, 1 task | $36 | $1.20 |
| Worker (Spot, mostly at zero) | $2-5 | $0.10 |
| NAT gateway (one) | $33 + data | $1.10 |
| Load balancer | $18 | $0.60 |
| RDS `db.t4g.micro` + 20 GB | $14 | $0.50 |
| Qdrant `t3.small` + 20 GB | $18 | $0.60 |
| Secrets, KMS, alarms, logs, Route 53 zone | $10 | $0.35 |
| **Total** | **about $130-140** | **about $4.40** |

That is roughly **£3 to £4 per day** (at about $1.30 to the pound, which moves). A demo that runs for a day or two and is then torn
down costs a few pounds; the same environment left running for a month costs about $130. **What decides the bill is whether you
tear it down**, which is why [teardown](teardown.md) matters more than any single saving here.

### Why the NAT gateway was not removed for the demo

Removing the NAT would mean putting tasks in public subnets with public IPs. It was not built, for two reasons:

1. **It saves little.** Each public IPv4 address is billed per hour (about $3.60 per month per address), so every task
   that gets one adds cost. With 2 to 3 tasks that gives back a large part of the NAT's $33.
2. **Qdrant and the database would still need to reach AWS.** They stay in private subnets. The Qdrant host has to reach ECR
   (to pull its image) and Secrets Manager and Session Manager. Without a NAT that needs VPC interface endpoints for ECR
   (two), Secrets Manager, and Systems Manager (three), about six endpoints at roughly $7 per month each, about $44 per
   month, which is more than the NAT it replaces.

It would also widen the attack surface (task network interfaces with public addresses, protected only by security groups).
So the NAT stays, and a short demo with a clear teardown is the cheaper and safer way to save money.

## Biggest levers

1. **NAT gateway.** One shared NAT (`single_nat_gateway = true`) halves the fixed cost but makes egress single-AZ. The S3
   gateway endpoint already keeps S3 and ECR layer traffic off the NAT. VPC interface endpoints (ECR, Secrets Manager, SQS,
   CloudWatch Logs) cost about $7/month each per AZ and pay off only at higher data volumes.
2. **Task counts.** Dev can run `api_min_count = 1`, `worker_min_count = 1`. The worker can also be scaled to zero overnight in
   non-production by setting its minimum to 0 (the first job then waits for a task to start and load the model).
3. **Multi-AZ RDS** is the largest single prod premium; it buys automatic failover.
4. **Log volume.** `log_retention_days` (14 dev, 90 prod example) and the INFO-level request telemetry dominate CloudWatch cost.
   Container Insights adds metrics cost per task.
5. **Savings plans / ARM.** Compute savings plans apply to Fargate. Graviton (`cpu_architecture = "ARM64"`) is about 20%
   cheaper but is untested here: CI builds `linux/amd64` only.

## Cost guardrails

- `db_max_allocated_storage` caps RDS autoscaling; `worker_max_count` / `api_max_count` cap scale-out.
- Uploaded originals expire after 30 days; ECR keeps the 30 newest images; DLQ messages expire after 14 days.
- `budget_email` creates a monthly AWS Budget for this environment with alerts at 50% and 80% of actual spend and 100% of forecast.
  An account-wide budget is still worth having and is not managed here.

## Tear-down

See [teardown](teardown.md) for the full procedure and the checks that nothing is still billing. In short, destroying an environment is a deliberate, multi-step act: RDS has `deletion_protection` (set `db_deletion_protection = false`
and apply first), the document bucket must be emptied (it is versioned), ECR repositories with images must be emptied, and
secrets enter a 7/30 day deletion window. Take a manual RDS snapshot before destroying anything you might need.
