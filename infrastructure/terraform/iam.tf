# infrastructure/terraform/iam.tf
# Service accounts and their bindings.

# ── Runtime identity for the production VM ─────────────────────────────────────
# Attached to odoo-19-prod during the Phase 4 window (see compute.tf — the field
# cannot be changed while the instance runs).

resource "google_service_account" "prod_vm" {
  account_id   = "odoo-prod-vm"
  project      = var.project_id
  display_name = "Odoo production VM runtime"
}

resource "google_project_iam_member" "prod_vm" {
  for_each = toset([
    # The Ops Agent is ALREADY installed and running on the VM, and has been
    # dropping every metric and log it collects because the current service
    # account cannot write them. These two roles are what make the existing
    # agent start working — nothing needs installing.
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    # Pull deploy images built by Cloud Build.
    "roles/artifactregistry.reader",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.prod_vm.email}"
}

# ── CI/CD identity ─────────────────────────────────────────────────────────────

resource "google_service_account" "cloudbuild" {
  account_id   = "odoo-cloudbuild"
  project      = var.project_id
  display_name = "Odoo Cloud Build CI/CD"
}

resource "google_project_iam_member" "cloudbuild" {
  for_each = toset([
    "roles/artifactregistry.writer", # push images
    "roles/logging.logWriter",       # required for a custom build service account
    "roles/compute.osAdminLogin",    # SSH to the VM with sudo, via OS Login
    "roles/compute.viewer",          # resolve the instance before connecting
    "roles/iap.tunnelResourceAccessor",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.cloudbuild.email}"
}

# Deliberately NOT granted roles/storage.objectViewer. Source arrives from the
# GitHub App, not a GCS tarball, so the build never reads a bucket. Add it only
# if a manual `gcloud builds submit` is ever needed.

# ── SSH into a VM that has a service account attached ──────────────────────────
# Non-obvious requirement: OS Login roles alone are not enough. The caller must
# also be able to act as the service account the TARGET INSTANCE runs as, or the
# connection is refused after authentication succeeds.
resource "google_service_account_iam_member" "cloudbuild_actas_prod_vm" {
  service_account_id = google_service_account.prod_vm.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.cloudbuild.email}"
}

# ── Letting Cloud Build USE the custom build service account ───────────────────
#
# Same trap that bit the WhatsApp platform. A trigger running as a user-managed
# service account needs Cloud Build's SERVICE AGENT to be able to mint tokens for
# it. The console does this silently; the API does not.
#
# The failure is delayed and misleading: creating the trigger SUCCEEDS, because
# the principal running Terraform has actAs via Owner. Only the first BUILD
# fails, with an error that reads like a Cloud Build fault rather than a missing
# binding.
#
# CAREFUL — the project has two Cloud Build identities and they are not
# interchangeable:
#
#   <PROJECT_NUMBER>@cloudbuild.gserviceaccount.com
#       LEGACY DEFAULT build account — the identity a build runs as when none is
#       specified.
#
#   service-<PROJECT_NUMBER>@gcp-sa-cloudbuild.iam.gserviceaccount.com
#       SERVICE AGENT — Google's control-plane identity, and the one that
#       impersonates a user-specified service account on the build's behalf.
#
# It is the SERVICE AGENT that needs this. Granting it to the legacy account
# instead leaves the real impersonation path unauthorised while a binding sits
# there looking correct.
#
# The address is composed explicitly rather than read from
# google_project_service_identity, because that resource returns the LEGACY
# account for cloudbuild.googleapis.com, not the service agent.
resource "google_service_account_iam_member" "cloudbuild_agent_token_creator" {
  service_account_id = google_service_account.cloudbuild.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-cloudbuild.iam.gserviceaccount.com"
}

data "google_project" "this" {
  project_id = var.project_id
}

# ── Pre-existing accounts, imported ────────────────────────────────────────────

# Attached to odoo-19-prod today. BigQuery-only — genuinely least privilege, and
# the reason the Ops Agent cannot write anything.
#
# Keep it after the Phase 4 swap until BigQuery is confirmed dead. Deleting a
# service account is not reversible, and note that entrypoint.sh runs
# `import bigquery` under `set -e`: drop the dependency without removing that
# probe and the container stops booting.
resource "google_service_account" "bq_access" {
  account_id   = "odoo-bq-access"
  project      = var.project_id
  display_name = "odoo-bq-access"
  description  = "Service account for Odoo VM to access BQ in cleardeals-459513"
}

# ── Grants on the CURRENT VM identity ──────────────────────────────────────────
#
# The roles above are on odoo-prod-vm@, which the VM will run as AFTER the
# Phase 4 service-account swap. Until then it still runs as odoo-bq-access@, and
# the pipeline needs these on the account actually attached to the instance.
#
# This gap cost two failed deploys. Granting a permission to the identity a
# resource WILL have is not the same as granting it to the one it HAS.
#
# Both bindings become removable once Phase 4 attaches odoo-prod-vm@ — but
# remove them in that same change, not before.
resource "google_project_iam_member" "bq_access_artifact_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.bq_access.email}"
}

# Required for `gcloud compute ssh` to reach an instance that has a service
# account attached: the caller must be able to act as THAT account. OS Login
# roles alone are not sufficient.
resource "google_service_account_iam_member" "cloudbuild_actas_bq_access" {
  service_account_id = google_service_account.bq_access.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.cloudbuild.email}"
}

resource "google_service_account" "stage_vm" {
  account_id   = "odoo-stage-vm"
  project      = var.project_id
  display_name = "Odoo staging VM (Pub/Sub publisher)"
}

# ── BigQuery: what the Phase 4 service-account swap would have broken ──────────
#
# The pre-flight audit for Phase 4 found that BigQuery is NOT dead. It is used
# by 22 files across lead_suggestor and leads/models/lead_score.py — both
# installed in production. The data lives in a DIFFERENT project,
# cleardeals-459513, where odoo-bq-access@ holds four roles.
#
# odoo-prod-vm@ had none of them. Attaching it to the VM as originally planned
# would have silently broken lead scoring and property suggestions: no startup
# error, no failed health check, just queries failing at runtime — the same
# shape of failure as the addons-volume outage.
#
# These grants make odoo-prod-vm@ a strict SUPERSET of odoo-bq-access@ in both
# projects, verified role-by-role before the swap. Permission-neutral is the
# property that makes the swap safe.
#
# dataEditor is replicated rather than reduced. The code appears read-only
# (only .query() calls, no insert_rows or load_table), so this is probably
# reducible to dataViewer + jobUser — but tightening it is a separate change
# that deserves its own verification, not a rider on a migration.
locals {
  bigquery_roles = [
    "roles/bigquery.dataEditor",
    "roles/bigquery.dataViewer",
    "roles/bigquery.jobUser",
    "roles/bigquery.user",
  ]
}

resource "google_project_iam_member" "prod_vm_bigquery" {
  for_each = toset(local.bigquery_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.prod_vm.email}"
}

# The warehouse project. Declared here because the Odoo VM's identity is what
# needs access to it; the project itself is not managed by this module.
resource "google_project_iam_member" "prod_vm_bigquery_warehouse" {
  for_each = toset(local.bigquery_roles)
  project  = var.bigquery_project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.prod_vm.email}"
}
