# Teardown

How to remove an environment completely, what is kept on purpose, what Terraform does **not** remove (and keeps billing),
and how to prove nothing is left. These steps have not been run against a real account; do the first one on a throwaway
`dev` environment and fix this page with what you learn.

Everything here is done by a person. Nothing in this repository runs `terraform destroy`.

## 1. Decide what to keep

| Data | Default behaviour | If you want it |
|---|---|---|
| Database | A final snapshot `<project>-<env>-final` is taken on destroy **unless** `db_skip_final_snapshot = true` (the dev example sets it to true so demos leave nothing behind) | Set `db_skip_final_snapshot = false` and apply before destroying, or run `aws rds create-db-snapshot` yourself |
| Qdrant index | The volume is deleted. **Existing snapshots are not** (see step 4) | Keep the newest snapshot; delete the rest |
| Uploaded documents | The bucket is versioned and must be emptied by you, so nothing is deleted silently | Copy out what you need first |
| Secrets | Enter a 7 or 30 day recovery window | `aws secretsmanager restore-secret` within the window |
| Terraform state | Lives in your backend, untouched | Keep it until the destroy has finished |

Take a manual database snapshot if there is any chance you want the data back.

## 2. Remove the guards (one apply)

The safeguards are on purpose, so destroy fails until you lift them. Edit your tfvars, review the plan, apply.

```hcl
db_deletion_protection = false
# db_skip_final_snapshot = true   # only if you do NOT want a final snapshot
```

`prod` also has load balancer deletion protection (on when `environment = "prod"`); a demo environment does not.

## 3. Empty what Terraform will not empty

Terraform refuses to delete a non-empty S3 bucket or ECR repository. Empty them first.

```bash
ENV=dev
BUCKET=$(terraform -chdir=infra/terraform output -raw documents_bucket)

# S3: delete every object version and delete marker (the bucket is versioned)
aws s3api list-object-versions --bucket "$BUCKET" --output json \
  --query '{Objects: [].{Key: Key, VersionId: VersionId}}' > /tmp/versions.json   # review it
# If it lists objects: aws s3api delete-objects --bucket "$BUCKET" --delete file:///tmp/versions.json
# (run again with --query for DeleteMarkers; repeat until the list is empty; delete-objects takes 1000 at a time)

# ECR: remove the images in all three repositories
for repo in api worker qdrant-mirror; do
  aws ecr list-images --repository-name docchat/$ENV/$repo --query 'imageIds[*]' --output json > /tmp/images.json
  # If it lists images: aws ecr batch-delete-image --repository-name docchat/$ENV/$repo --image-ids file:///tmp/images.json
done
```

Also drain the queue if you care about its contents (`aws sqs purge-queue`); destroy removes the queues regardless.

## 4. Destroy

```bash
terraform -chdir=infra/terraform plan -destroy -var-file=dev.tfvars -out=destroy.tfplan
# READ the plan. Check it names only this environment's resources.
terraform -chdir=infra/terraform apply destroy.tfplan      # a person runs this
```

This removes the services, load balancer, NAT gateway and its address, instances, volumes, database, queues, bucket,
repositories, log groups, alarms, dashboard, budget, VPC, hosted zone and the roles and policies Terraform created.

## 5. What survives destroy and may keep billing

| Left behind | Why | Remove it |
|---|---|---|
| **Qdrant EBS snapshots** | Data Lifecycle Manager stops, but snapshots it already made stay | `aws ec2 describe-snapshots --owner-ids self --filters Name=tag:Project,Values=docchat Name=tag:Environment,Values=$ENV`, then `delete-snapshot` for each you do not need |
| **RDS final snapshot and manual snapshots** | Kept on purpose (and manual ones are never touched) | `aws rds describe-db-snapshots`, then `delete-db-snapshot` |
| Secrets in their recovery window | Deletion is scheduled, not immediate | Wait 7 or 30 days, or `aws secretsmanager delete-secret --force-delete-without-recovery` to remove now |
| KMS keys | Scheduled for deletion after a waiting period (default 30 days) | Nothing to do; keys pending deletion are not billed |
| CloudWatch log groups created by something else, and VPC flow log groups | Only Terraform-managed groups are removed | `aws logs describe-log-groups --log-group-name-prefix /docchat/` |
| GitHub OIDC provider | Shared by the whole account, created only if you let Terraform create it | Leave it unless nothing else uses it |
| Remote state bucket and lock table | Outside this configuration | Keep, or delete when you are sure |

## 6. Check that nothing is still billing

Everything this configuration creates is tagged `Project=docchat` and `Environment=<env>`, so one query finds survivors:

```bash
aws resourcegroupstaggingapi get-resources \
  --tag-filters Key=Project,Values=docchat Key=Environment,Values=$ENV \
  --query 'ResourceTagMappingList[].ResourceARN' --output text
```

Expect only the items in section 5. Then check the things that bill by the hour even when "unused":

```bash
aws ec2 describe-nat-gateways --filter Name=state,Values=available,pending --query 'NatGateways[].NatGatewayId'
aws ec2 describe-addresses --query 'Addresses[?AssociationId==null].PublicIp'     # unattached Elastic IPs bill
aws elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerArn'
aws ec2 describe-volumes --filters Name=status,Values=available --query 'Volumes[].VolumeId'   # unattached volumes bill
aws ec2 describe-vpc-endpoints --query 'VpcEndpoints[].VpcEndpointId'
aws rds describe-db-instances --query 'DBInstances[].DBInstanceIdentifier'
aws ecs list-clusters
```

Finally, open **Cost Explorer** (grouped by service) the next day and the day after. Costs are reported with a delay of up to a
day, so a clean tag query plus two quiet days is the real proof. The Budget created with `budget_email` is deleted by
destroy; keep an account-level budget if you want a permanent safety net.

## If destroy fails

- *Bucket or repository not empty:* repeat step 3. Versioned buckets also need delete markers removed.
- *Database deletion protection:* step 2 was not applied.
- *Security group or subnet in use:* a leftover network interface; find it with
  `aws ec2 describe-network-interfaces --filters Name=vpc-id,Values=<vpc id>`, wait for ECS tasks to stop, then retry.
- *State drift after manual changes:* `terraform plan -destroy` shows it; fix or `terraform state rm` the resource, then delete it by hand.
