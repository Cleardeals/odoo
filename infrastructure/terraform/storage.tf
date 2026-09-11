# infrastructure/terraform/storage.tf
# Until this module existed the project had NO buckets at all.

resource "google_storage_bucket" "tfstate" {
  name     = "cleardeals-odoo-tfstate"
  project  = var.project_id
  location = "US-CENTRAL1"

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  # The point of versioning on a state bucket: a truncated or corrupted state
  # write is recoverable from the previous generation.
  versioning {
    enabled = true
  }

  # This bucket holds the state that describes it. Terraform can create it but
  # must never be allowed to destroy it.
  lifecycle {
    prevent_destroy = true
  }
}

resource "google_storage_bucket" "backups" {
  name     = "cleardeals-odoo-backups"
  project  = var.project_id
  location = "US-CENTRAL1"

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }

  # No deletion lifecycle rule on purpose. Backups ageing out silently is a worse
  # failure than paying for storage.
  lifecycle {
    prevent_destroy = true
  }
}

# ── Backups: write and read, but NOT delete ────────────────────────────────────
#
# objectCreator alone is not enough — `gcloud storage cp` issues a GET before
# writing and 403s without objectViewer. The obvious fix is objectAdmin; this
# grants creator + viewer instead, so a VM can write and verify its own backups
# but cannot delete them. If the box is ever compromised, the backups survive it.
# Keys are built from var.project_id rather than from the service-account
# resources' .email attributes. That is deliberate: a for_each whose KEYS depend
# on a not-yet-created resource cannot be evaluated during `terraform import`,
# which fails the whole import run with "Invalid for_each argument" — including
# for unrelated resources. The emails are fully determined by the account ids
# anyway, so nothing is lost but the implicit dependency, restored by depends_on.
locals {
  backup_writers = [
    "serviceAccount:odoo-bq-access@${var.project_id}.iam.gserviceaccount.com", # current VM SA
    "serviceAccount:odoo-prod-vm@${var.project_id}.iam.gserviceaccount.com",   # after Phase 4
  ]
}

resource "google_storage_bucket_iam_member" "backup_create" {
  for_each = toset(local.backup_writers)
  bucket   = google_storage_bucket.backups.name
  role     = "roles/storage.objectCreator"
  member   = each.value

  depends_on = [google_service_account.bq_access, google_service_account.prod_vm]
}

resource "google_storage_bucket_iam_member" "backup_read" {
  for_each = toset(local.backup_writers)
  bucket   = google_storage_bucket.backups.name
  role     = "roles/storage.objectViewer"
  member   = each.value

  depends_on = [google_service_account.bq_access, google_service_account.prod_vm]
}

# NOTE: GCS legacy bindings still give any project Editor legacyObjectOwner on
# this bucket, so backups are not immutable against a project-level principal.
# Hardening that is separate work — recorded here so it is not mistaken for done.
