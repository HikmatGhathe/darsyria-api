# DarSyria on Google Cloud

This is a separate Terraform root for a new Compute Engine deployment. The
existing Azure infrastructure remains in `../terraform`, with separate state.
These files prepare infrastructure; they do not migrate data, change DNS, or
deploy the application automatically.

## Target and cost

- Use a Google Cloud project linked to an active billing account.
- Defaults: Frankfurt `europe-west3`, zone `europe-west3-a`, `e2-standard-2`
  (2 vCPUs, 8 GiB RAM), Ubuntu 24.04, one 50 GB balanced persistent boot disk.
- The VM runs continuously. There is no automatic business-hours shutdown.
- A static external IPv4, disk capacity, snapshot storage, and network traffic
  cost extra. Check the region-specific estimate in the
  [Google Cloud calculator](https://cloud.google.com/products/calculator).
- If the deployment relies on promotional credits, check their balance,
  expiry, and eligibility in the linked billing account before applying.
- Set a billing budget that tracks usage before promotional credits, so trial
  credits do not conceal consumption. Ordinary budget alerts are notifications,
  not a spending cap. Stopping the VM still leaves disk, snapshots, and reserved
  IP charges. Azure remains separately billable until deliberately retired.

The network exposes only TCP 80/443 publicly. SSH uses IAP and OS Login; ports
5432, 8000, 3000, and 8081 remain private. The designated admin receives
`roles/compute.osAdminLogin`, `roles/iap.tunnelResourceAccessor`, and service
account user access to the VM's dedicated service account. The VM service
account itself receives no project roles.

## 1. Get these files into Cloud Shell

Use one Terraform working directory consistently. Do not run a second copy of
this configuration with empty state against the same resource names.

In Cloud Shell, clone the repository into your persistent home directory.
Check out the branch or release containing this Terraform root, then enter
`darsyria-api/infra/terraform-gcp`. If you transfer the root from an existing
checkout, include `startup.sh` and the committed `.terraform.lock.hcl`.

## 2. Authenticate and prepare a plan

The operator needs permission to enable APIs, create Compute Engine resources
and service accounts, and grant the listed IAM roles. A project owner normally
has these permissions; organizational restrictions can still apply.

Cloud Shell normally provides Terraform with credentials for the signed-in
user. If running from a local workstation, first run
`gcloud auth application-default login`. Never upload a service account key to
this repository.

```bash
export GCP_PROJECT_ID='YOUR_PROJECT_ID'
gcloud config set project "$GCP_PROJECT_ID"
gcloud billing projects describe "$GCP_PROJECT_ID"
gcloud services enable serviceusage.googleapis.com cloudresourcemanager.googleapis.com \
  --project="$GCP_PROJECT_ID"
```

Replace `YOUR_PROJECT_ID` with the ID of the target project before running
these commands. Confirm `billingEnabled: true` and the intended billing
account. Terraform enables the Compute, IAM, IAP, and OS Login APIs during
apply.

On the first setup, generate your local variables using the signed-in Google
user email. Edit the existing `terraform.tfvars` on subsequent runs. Machine
size, region, disk size, and retention use the defaults documented above
unless overridden.

```bash
(
  umask 077
  set -o noclobber
  printf 'project_id = "%s"\nadmin_email = "%s"\n' \
    "$GCP_PROJECT_ID" "$(gcloud config get-value account)" > terraform.tfvars
)
terraform init
terraform fmt -check
terraform validate
terraform plan -out=gcp.tfplan
```

Alternatively, copy `terraform.tfvars.example` to `terraform.tfvars` and replace
`YOUR_PROJECT_ID` and `you@example.com`. Supply the email of a Google user
account for the administrator.

Review the plan and regional cost estimate. A first deployment should create
only the new GCP resources, enable the listed APIs, and add the specified IAM
members. It must not destroy resources or change any Azure resources. If names
already exist, stop and inspect ownership/state instead of deleting them.

Once ready to provision the reviewed plan (this starts billable resources):

```bash
terraform apply gcp.tfplan
terraform output
```

State is initially local and ignored by Git. Back up `terraform.tfstate` and
its backup securely after apply, along with the exact configuration and lock
file. State and plan files can contain sensitive data. Do not upload them into
Git or chat. Before CI applies or multiple operators manage this stack, migrate
this same state to a restricted, versioned GCS backend with locking; do not
initialize an unrelated state. Terraform supports `terraform init -migrate-state`
after configuring that backend.

The GitHub Terraform workflow checks formatting and validation for both roots
using the committed provider lock files. It needs no cloud credentials.

## 3. Connect and check the VM

Run the SSH command printed by `terraform output -raw ssh_command`. It uses
the project, VM name, and zone recorded in Terraform state.

The first boot installs Docker Engine, Compose, and Git from the appropriate
Ubuntu/Docker repositories. Allow a few minutes. On the VM:

```bash
sudo journalctl -u google-startup-scripts.service --no-pager -n 100
sudo docker version
sudo docker compose version
df -h /
```

OS Login chooses your Linux username from your Google identity; it is not
`azureuser`. Use `sudo docker`, rather than assuming Docker group membership.
If IAP/OS Login access fails immediately after apply, allow IAM propagation
and confirm you are using the email configured in `admin_email`.

The disk is separate from the VM lifecycle and is not automatically deleted
with the VM. Both Terraform resources have `prevent_destroy`; the VM also has
Compute Engine deletion protection. OS-image family changes are ignored after
disk creation so they cannot replace the disk containing production data.
Patching the OS and application remains the operator's responsibility.

The startup script runs on boot and installs missing packages. Updating its
metadata does not replace the VM or execute it immediately. To deliberately
rerun it, use `sudo google_metadata_script_runner startup` on the VM.

## 4. Prepare application code and a migration rehearsal

Clone the three repositories as sibling directories in your OS Login home:

```text
~/darsyria-api/
~/darsyria/
~/darsyria-alerts/
```

Check out the intended application release in each repository. The production
steps below assume a release that includes the alerts service and the
versioned chatbot corpus. The corresponding Compose file in `darsyria-api`
builds the two sibling folders.

Transfer `.env` through an authenticated encrypted channel, keep it mode 600,
and keep it outside Git. Do not put application secrets in Terraform variables
or instance metadata. Preserve production `SECRET_KEY`, `JWT_SECRET`, database
credentials, and webhook secrets during the final migration; changing them can
invalidate sessions or integrations. Check both public and private R2 bucket
settings. Keeping the same public domains avoids changing OAuth callbacks and
webhook URLs; test those integrations after cutover.

Before a production freeze, rehearse a restore into a fresh, separate target
database using a copy of production backups. The API starts its scheduler and
startup maintenance unconditionally. **Do not start a rehearsal API with
production email credentials, writable production R2 buckets, or the live
database.** Use sandbox credentials/buckets and a separate test domain; keep
the alerts service in `DIGEST_DRY_RUN=true`. Avoid exposing copied personal data
on an unrestricted staging site. Database-only restore checks can run with
just the Postgres container and no API or email service at all.

Check source database size, Docker disk usage, and free space before choosing
the final disk size. The boot disk holds all Docker volumes and build caches;
50 GB is an initial allocation, not a capacity guarantee. Do not prune Docker
volumes to recover space. Never use `docker compose down -v` on either data copy.

## 5. Final database transfer

These commands assume the shared database role configured by `POSTGRES_USER`
and the default alerts database name `darsyria_alerts`. Adapt names before
running if `ALERTS_POSTGRES_DB` is different. If alerts uses a separate database
role, recreate that role securely and arrange the required ownership/grants
before restoring; database dumps do not create roles. Keep the PostgreSQL major
version at 16 and verify the source/target `vector` extension versions during
the rehearsal. Do not mix a PostgreSQL upgrade into this move.

1. Freeze deployments in all three repositories. Their current workflows SSH
   to `darsyria.me` as `azureuser`. Once DNS changes, they will hit the new
   server using an incompatible authentication method. Disable those deploy
   workflows until explicitly replaced with Google authentication/IAP or a
   suitable image-based deployment flow. Keep the Azure power schedule from
   stopping the source during the maintenance window.
2. Lower the website and API DNS TTL ahead of time. Announce a maintenance
   window and account for delayed/retried inbound email webhooks.
3. On **Azure**, stop every application writer and public entry point. Keep
   PostgreSQL running for the final logical backups:

```bash
cd ~/darsyria-api
sudo docker compose --profile prod stop caddy frontend api
```

If the Azure release defines the `alerts` service, stop it with `sudo docker
compose --profile prod stop alerts`. Confirm that Postgres is running and all
application services are stopped with `sudo docker compose --profile prod ps`
before dumping either database.

```bash
umask 077
sudo docker compose exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > darsyria-final.dump
sudo docker compose exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -d darsyria_alerts -Fc' > alerts-final.dump
sha256sum darsyria-final.dump alerts-final.dump
```

If the alerts database does not exist on the source, verify it has never been
used; do not ignore a failed dump of a database that should contain data. Also
stop any external scripts or sessions that write directly to the source DB.

4. Transfer the dumps securely to the new VM and compare checksums. For IAP,
   `gcloud compute scp --tunnel-through-iap --project=... --zone=...` supports
   uploads from Cloud Shell. Files must first be securely copied there from
   the source. Do not put dumps in public buckets or the repository.
5. On the **GCP VM**, use a fresh target Postgres volume and the final `.env`.
   If rehearsal used this volume, preserve that copy and choose a new Compose
   project name/volume for the final restore; do not restore over its existing
   tables. Container names are fixed, so stop/remove rehearsal containers
   while preserving their volumes before using the new project name. Use the
   same project name consistently on every subsequent Compose command.
6. Start only Postgres, then wait for its health check to become healthy:

```bash
cd ~/darsyria-api
sudo docker compose up -d postgres
sudo docker compose ps postgres
```

Fresh-volume init creates the main database, `vector`, and the default alerts
database. Check `db-init` if using custom names; create a missing custom alerts
database before the restore. Do not start API/Alembic or alerts/Flyway yet.

```bash
sudo docker compose exec -T postgres sh -c \
  'pg_restore --exit-on-error --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < darsyria-final.dump
sudo docker compose exec -T postgres sh -c \
  'pg_restore --exit-on-error --no-owner --no-acl -U "$POSTGRES_USER" -d darsyria_alerts' \
  < alerts-final.dump
```

Stop on any restore error. Compare critical table counts, migration versions,
and representative records against the frozen source. Confirm that `vector`
exists. Rehearse the actual restore and application checks before doing this
under the final maintenance window.

## 6. Start, verify, and switch DNS

Confirm production `.env` settings: `APP_ENV=production`, `SITE_DOMAIN`,
`FRONTEND_URL`, `ALLOWED_ORIGINS`, `NEXT_PUBLIC_SITE_URL`, `NEXT_PUBLIC_API_URL`,
`GOOGLE_REDIRECT_URI`, and external-service credentials. Next.js public URLs
are build arguments, so rebuild when changing them. Compose already uses
`http://api:8000` for server-side frontend requests.

With source writers stopped and the final restore verified:

```bash
sudo docker compose --profile prod build
sudo docker compose --profile prod up --wait api frontend alerts
sudo docker compose --profile prod ps
curl --fail http://localhost:8000/health
curl --fail http://localhost:8000/health/db
curl --fail http://localhost:8081/actuator/health
sudo docker compose exec -T api python -m scripts.ingest_articles --prune
```

API startup runs Alembic and alerts startup runs Flyway. The ingestion command
synchronizes the restored knowledge base with the articles in the target
release. Resolve migration, health check, or ingestion failures before
starting Caddy. Keep one API replica for the in-process daily digest. Keep
`DIGEST_DRY_RUN=true` for the Java service until the alerts rollout enables
real sending.

Before changing public DNS, validate application behavior through an SSH tunnel
or a rehearsed staging domain. For final-domain HTTPS before DNS propagation,
use a separately prepared certificate/DNS challenge or carefully migrate the
existing Caddy TLS storage securely; a hosts-file override alone does not make
Let's Encrypt HTTP validation reach GCP. Otherwise plan certificate issuance
as part of the maintenance window after DNS moves. Warm and check the chatbot
embedding model before reopening traffic; its cache can also be transferred
from the source to avoid downloading it again. Start Caddy with `sudo docker
compose --profile prod up --wait caddy` once the application checks pass.

Update the website and `api` DNS records to `terraform output -raw
public_ip_address` from the Terraform directory. Audit any existing AAAA or
proxy/origin settings too. Verify HTTPS, Google and magic-link login, listings,
uploads, private verification documents, chatbot retrieval, enquiries, email
webhooks, and alerts health against the new server. `/internal/*` must remain
blocked by Caddy. Check logs and database counts before ending maintenance.

The same signing keys and restored auth tables should preserve existing
sessions, but verify this with a real session. Keep Azure writers and
schedulers stopped after cutover to prevent duplicate sends or split data.

## 7. Rollback, backups, and follow-up work

- Before GCP accepts writes, rollback can restart the frozen Azure application
  and restore DNS. After GCP accepts writes, stop writers first and reconcile
  or migrate the new data back. DNS rollback alone would lose new changes.
- Daily disk snapshots are scheduled at 04:00 UTC with seven-day retention by
  default. They are crash-consistent and contain the entire boot disk,
  including secrets. Keep access restricted. Retention follows Google snapshot
  policy semantics; failed snapshot schedules can affect cleanup.
- Before production cutover, schedule independent off-VM logical backups of
  **both** databases and test a restore. This Terraform does not create a
  logical-backup job or backup bucket. Disk snapshots alone do not verify that
  a database restore will succeed.
- This single VM is a single point of failure. Add monitoring for availability,
  disk usage, backup failures, and actual billing consumption. Database and
  cache growth, build cache, and logs all consume the same disk.
- Replace the Azure SSH deployment workflows in all three repositories before
  re-enabling automatic deploys. Prefer GitHub OIDC/Workload Identity Federation
  and IAP rather than service account keys or opening SSH to the world. Serialize
  deployments across repositories to avoid concurrent Compose builds/migrations.
- The existing Azure scheduling workflow manages only the Azure VM. Stop it
  when Azure is retired. A GCP shutdown schedule would also stop the website,
  webhooks, and in-process digest; introduce one only if that outage is intended.
- Retire Azure deliberately after an agreed observation period and verified
  backups. Do not destroy it through this GCP Terraform root. To resize this VM,
  plan a maintenance window and explicitly allow stopping for the update;
  `allow_stopping_for_update` defaults to false here.

## References

- [IAP TCP forwarding](https://docs.cloud.google.com/iap/docs/using-tcp-forwarding)
- [OS Login setup](https://docs.cloud.google.com/compute/docs/oslogin/set-up-oslogin)
- [Docker on Ubuntu](https://docs.docker.com/engine/install/ubuntu/)
- [Terraform GCS state backend](https://developer.hashicorp.com/terraform/language/backend/gcs)
- [Google Cloud budgets](https://docs.cloud.google.com/billing/docs/how-to/budgets)
