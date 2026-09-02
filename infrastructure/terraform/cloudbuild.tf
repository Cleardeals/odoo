# infrastructure/terraform/cloudbuild.tf
# The CI/CD entry points.
#
# Before these existed, production deploys were a GitHub Actions workflow that
# SSHed in with a long-lived private key from a repo secret, ran
# `docker compose build` ON the production VM, and reported success whether or
# not Odoo came back up. That workflow is deleted in the same change that adds
# these.
#
# ── ONE-TIME MANUAL STEP ──────────────────────────────────────────────────────
# Terraform cannot create the GitHub App connection. A GitHub org admin installs
# the Cloud Build GitHub App and grants it this repository, once, at
# https://console.cloud.google.com/cloud-build/triggers/connect
#
# Until then keep cloudbuild_github_connected = false: these resources are
# skipped and the rest of the module still applies cleanly.

locals {
  gh_owner = split("/", var.github_repo)[0]
  gh_name  = split("/", var.github_repo)[1]

  # Two switches, deliberately independent. The CI trigger builds no production
  # image and touches no VM. The CD trigger deploys to production. Tying them to
  # one flag would force that blast-radius increase to be accepted just to get
  # pull-request checks.
  ci_count = var.cloudbuild_github_connected ? 1 : 0
  cd_count = var.cloudbuild_github_connected && var.cloudbuild_cd_enabled ? 1 : 0
}

# ── CI: pull requests ──────────────────────────────────────────────────────────
resource "google_cloudbuild_trigger" "ci" {
  count       = local.ci_count
  project     = var.project_id
  location    = "global"
  name        = "odoo-ci-pull-request"
  description = "Tests, config checks, and image-contents verification. Builds no production image, deploys nothing."

  github {
    owner = local.gh_owner
    name  = local.gh_name
    pull_request {
      # Both branches that can reach production: 19.0 directly, and
      # development_19 which is merged into it.
      branch = "^(19\\.0|development_19)$"
      # comment_control is deliberately omitted. Its API default is stored as
      # UNSET, so setting it explicitly produces a permanent one-line diff on
      # every plan — which trains people to skim plans instead of read them.
    }
  }

  filename        = "cloudbuild.ci.yaml"
  service_account = google_service_account.cloudbuild.id
}

# ── CD: push to 19.0 ───────────────────────────────────────────────────────────
#
# A merge STARTS this pipeline; it does not reach production unattended.
# approval_required holds every run until a human releases it.
#
# That gate is doing a job GitHub cannot do here. The intended design was branch
# protection — block the merge while CI is failing or still running — but GitHub
# refuses that on private repositories under a free plan (both branch protection
# and the newer rulesets API return 403). The merge button stays clickable on a
# red PR, so the gate moved one step later: a bad merge is possible, a bad
# DEPLOY is not.
resource "google_cloudbuild_trigger" "cd" {
  count       = local.cd_count
  project     = var.project_id
  location    = "global"
  name        = "odoo-cd-19"
  description = "Gate, build, push to Artifact Registry, and deploy to odoo-19-prod. Requires human approval."

  github {
    owner = local.gh_owner
    name  = local.gh_name
    push {
      branch = "^19\\.0$"
    }
  }

  filename        = "cloudbuild.yaml"
  service_account = google_service_account.cloudbuild.id

  substitutions = {
    _ZONE     = var.prod_zone
    _INSTANCE = "odoo-19-prod"
    _REGION   = var.region
  }

  approval_config {
    approval_required = true
  }

  # Deliberately NO included_files filter. A deploy trigger that skips files is
  # a deploy trigger that silently does not deploy something.
}
