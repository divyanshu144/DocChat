# Rollback

Rollbacks are fast because images are immutable per commit SHA (ECR tag immutability, 30 recent images kept) and ECS keeps
old task-definition revisions. None of these procedures has been rehearsed against a real account.

## Automatic: a bad deploy

Both ECS services use a **deployment circuit breaker with rollback**. If new tasks repeatedly fail to start or fail their
health check, ECS stops the rollout and returns to the last steady task definition on its own. The load balancer only
routes to tasks that pass `/api/v1/health/live`, and the rollout keeps `minimumHealthyPercent = 100`, so users keep being
served by the old tasks throughout.

The deploy workflow detects this: `aws ecs wait services-stable` also succeeds after a rollback, so it then checks that the
*primary* deployment is the revision it just registered and fails the job if not.

## Manual: roll back an application release

Find the previous revision and move the service to it. API and worker are independent; roll back only what is broken.

```bash
CLUSTER=docchat-prod
aws ecs list-task-definitions --family-prefix $CLUSTER-api --sort DESC --max-items 5
aws ecs update-service --cluster $CLUSTER --service api --task-definition <previous-arn>
aws ecs wait services-stable --cluster $CLUSTER --services api
```

Or re-run the Deploy workflow on the previous commit: its image is already in ECR, so it skips the build and only
registers a revision and updates the service.

### Is it safe to run old code against the new database?

Schema changes in this codebase are **additive** (new nullable or defaulted columns added by `_migrate` in
`app/core/database.py`; the `ingest_jobs` additions are `attempts`, `dedupe_key`, `lease_until`). Old code ignores columns
it does not know, so rolling the *application* back is safe. Keep it that way: a release that drops or renames a column
must be split into two releases (stop using it, then remove it later), or it cannot be rolled back.

If both services must go back, roll back the **worker first, then the API** (the reverse of deploy order). The API owns
schema changes and the worker only consumes them, so the worker should never run against a schema older than its code expects.

## Manual: roll back infrastructure

Terraform is the source of truth. Revert the commit that introduced the change, `terraform plan`, review, `apply`.
Things that make this safer or harder:

| Resource | Behaviour |
|---|---|
| RDS | `deletion_protection` on (default), final snapshot on destroy. Parameter-group and instance-class changes can restart or fail over the database; read the plan for "replace" and "forces new". |
| S3 documents | Versioned; an overwritten or deleted object can be restored from a previous version (within the lifecycle: 7 days for noncurrent versions). |
| Qdrant EC2 | `ignore_changes = [ami, user_data]`: Terraform will not replace the node that holds the index. Changing the instance type stops and restarts it. |
| ECR | Immutable tags; images older than the 30 most recent are expired, so keep a release you may need to return to within that window. |
| Secrets | Deleting a secret has a 7 or 30 day recovery window; restore it with `aws secretsmanager restore-secret`. |

## Manual: roll back a bad ingestion

Ingestion is idempotent and replacement is delete-then-upsert per source, so re-ingesting a source repairs it. To remove a
source entirely use `DELETE /api/v1/sources/<id>`. There is no bulk "undo this batch" tool.

## After any rollback

- Check `/api/v1/health` returns 200 and the dashboard shows 5xx and latency back to baseline.
- Check the ingest DLQ is empty (see [backups-and-recovery](backups-and-recovery.md) for redrive).
- Record what happened in `tasks/lessons.md`.
