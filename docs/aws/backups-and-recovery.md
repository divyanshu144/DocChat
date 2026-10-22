# Backups and recovery

**None of the restore procedures below has been executed.** They follow AWS documentation and the resource definitions in
`infra/terraform`; rehearse each in a non-production environment before relying on it.

## What is stored where, and how it is protected

| Data | Store | Protection | Loss window |
|---|---|---|---|
| Users, refresh tokens, conversations, folders, ingest job state | RDS PostgreSQL 16 | Automated backups with point-in-time restore (`db_backup_retention_days`, default 7, prod example 14); storage encrypted; optional Multi-AZ; final snapshot on delete; deletion protection | Up to ~5 minutes (PITR) |
| Vectors and chunk text (what retrieval searches) | Qdrant on EC2, EBS data volume | Daily EBS snapshots by Data Lifecycle Manager (`qdrant_snapshot_retention`, default 14); volume encrypted | Up to 24 hours, **crash-consistent only** |
| Uploaded originals | S3 (versioned, KMS) | Versioning; expire after `upload_retention_days` (default 30) | Not an archive: do not treat as the system of record |
| Source of truth for web and YouTube content | The internet | Re-ingestable from the URL | n/a |
| Secrets | Secrets Manager | 7/30 day recovery window; the RDS password is managed and rotated by RDS | n/a |
| Infrastructure | Terraform state (your backend) | Versioned remote state | n/a |

Qdrant is **derived data**: everything in it can be rebuilt by re-ingesting the sources, which is why it has daily
snapshots rather than continuous backup. Rebuilding is manual and slow (see below).

## Recovery objectives (design targets, not measured)

| Failure | Recovery | Expected impact |
|---|---|---|
| API task crash | ECS replaces it; ALB stops routing to it | None with 2+ tasks |
| Worker crash or deploy | Lease lapses, SQS redelivers, another worker re-claims the job | Jobs delayed by up to the visibility timeout (default 5 min) |
| RDS instance failure | Multi-AZ automatic failover (if enabled); otherwise restore | Minutes with Multi-AZ; much longer without |
| Qdrant instance hardware failure | `StatusCheckFailed_System` alarm triggers EC2 auto-recover (same volume, same IP) | Minutes; chat and ingestion fail meanwhile |
| Qdrant volume corruption or loss | Restore from snapshot (below) | Up to 24 h of changes lost |
| AZ outage | API/worker reschedule into the other AZ (2 AZs). RDS needs Multi-AZ; **Qdrant is in one AZ** | Qdrant outage until recovered |
| Region outage | Not covered | See [limitations](limitations.md) |

## Procedures

### Dead-letter queue (a job exhausted its retries)

The `ingest-dlq-not-empty` alarm fires. The job row is already `error` with the exception class; the cause is in the
worker log (filter by the job's `request_id`).

```bash
DLQ=$(terraform -chdir=infra/terraform output -raw ingest_dlq_url)
aws sqs get-queue-attributes --queue-url "$DLQ" --attribute-names ApproximateNumberOfMessages
# After fixing the cause, move everything back to the source queue:
aws sqs start-message-move-task \
  --source-arn   arn:aws:sqs:<region>:<account>:docchat-prod-ingest-dlq \
  --destination-arn arn:aws:sqs:<region>:<account>:docchat-prod-ingest
```

A redriven job is safe to run again: a job in `error` is re-claimable, a job already `done` is acknowledged and dropped,
and ingestion replaces the source rather than appending. PDFs need their S3 original, which is retained (`RETAIN_UPLOADS`)
until the bucket lifecycle expires it (30 days); after that the message fails permanently with "Object not found".
Messages never contain document text, so DLQ contents are safe to inspect but do contain submitted URLs.

### Restore the database

Point-in-time restore creates a **new** instance; it does not overwrite the old one.

```bash
aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier docchat-prod --target-db-instance-identifier docchat-prod-restore \
  --restore-time <UTC timestamp> --db-subnet-group-name docchat-prod \
  --vpc-security-group-ids <rds security group id> --no-publicly-accessible
```

Verify the data, then either (a) `terraform import` the restored instance over `aws_db_instance.main` after removing the
old one from state, or (b) for a quick recovery, set `DATABASE_HOST` on both task definitions to the restored endpoint and
deploy. The restored instance gets its own managed master secret; update the `DATABASE_PASSWORD` secret reference to match.
Take a manual snapshot (`aws rds create-db-snapshot`) before any risky migration.

### Restore Qdrant from a snapshot

1. Find the newest snapshot of the data volume: `aws ec2 describe-snapshots --filters Name=volume-id,Values=<qdrant_volume_id>`.
2. Stop the Qdrant instance (the API reports `/health` 503 and ingestion retries meanwhile).
3. Create a volume from the snapshot in the instance's AZ, encrypted, `gp3`.
4. Detach the old volume, attach the new one as `/dev/sdf`, start the instance. The filesystem is mounted by label and
   `qdrant.service` starts automatically.
5. Update `aws_ebs_volume.qdrant` in Terraform state (`terraform import` the new volume) so a later apply does not
   revert the attachment.
6. Re-ingest anything added after the snapshot time.

If there is no usable snapshot, rebuild: re-submit web and YouTube URLs; PDFs younger than the S3 retention can be
re-queued from their stored originals. **There is no bulk re-index command**; building one (list sources, enqueue each)
is the main missing piece of disaster recovery.

### Restore secrets

`aws secretsmanager restore-secret --secret-id docchat/prod/jwt-secret-key` within the recovery window. Rotating the JWT
key invalidates all sessions; users sign in again.

### Duplicate or stuck jobs

- *Stuck in `running` with no worker:* nothing to do; the lease lapses within ~3.3 minutes (two thirds of the 5 minute
  visibility timeout) and the redelivered message is re-claimed.
- *Message lost entirely* (job `queued` forever): jobs older than `INGEST_DEDUPE_WINDOW_S` no longer block resubmission;
  submit the source again.
- *Two jobs for one source:* serialised by the advisory lock and idempotent, so the result is the same.

## Backup verification checklist (do this before production)

- [ ] Restore an RDS snapshot to a scratch instance and run the app against it.
- [ ] Restore a Qdrant snapshot to a scratch instance and run a retrieval query.
- [ ] Redrive a deliberately failed job from the DLQ.
- [ ] Kill a worker mid-ingest and confirm the job completes elsewhere.
- [ ] Record the real durations; replace the design targets above.
