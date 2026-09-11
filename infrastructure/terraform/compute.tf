# infrastructure/terraform/compute.tf
# The two Odoo VMs, their disks, and their static addresses.
#
# Everything here was IMPORTED from infrastructure that already existed and had
# been managed by hand. The HCL was written to match what was already running —
# never the other way round. The gate for this module was a completely empty
# first plan; any diff meant the code was wrong, not production.

# ── Static addresses ───────────────────────────────────────────────────────────
# Both are IN_USE and are the addresses DNS points at. Releasing one means losing
# it to the regional pool, so these are effectively permanent.

resource "google_compute_address" "prod" {
  name         = "odoo-static-ip"
  project      = var.project_id
  region       = var.region
  address_type = "EXTERNAL"
  description  = "Static IP for Odoo Production access"
}

resource "google_compute_address" "stage" {
  name         = "odoo-stage-ip"
  project      = var.project_id
  region       = var.region
  address_type = "EXTERNAL"
}

# ── Boot disks ─────────────────────────────────────────────────────────────────
# Declared as standalone disks rather than inline boot_disk blocks because both
# have auto_delete = false and carry a snapshot schedule. An inline disk is
# destroyed with its instance; these deliberately outlive theirs.

resource "google_compute_disk" "prod" {
  name    = "odoo-19-prod"
  project = var.project_id
  zone    = var.prod_zone
  type    = "pd-balanced"
  size    = var.prod_boot_disk_size_gb
  image   = "https://www.googleapis.com/compute/v1/projects/ubuntu-os-cloud/global/images/ubuntu-2404-noble-amd64-v20251217"

  physical_block_size_bytes = 4096

  lifecycle {
    # The image is the one the disk was CREATED from and is pure history — the
    # running system has been patched far past it. Without this, every provider
    # upgrade that changes image handling threatens to recreate the boot disk of
    # production.
    ignore_changes = [image, snapshot]
  }
}

# The snapshot schedule is attached through its OWN resource, not a field on the
# disk. google_compute_disk has no resource_policies argument — attaching one
# inline fails validation.
resource "google_compute_disk_resource_policy_attachment" "prod_snapshot" {
  name    = google_compute_resource_policy.prod_4h.name
  disk    = google_compute_disk.prod.name
  project = var.project_id
  zone    = var.prod_zone
}

# ── Snapshot schedule — 4-hourly ───────────────────────────────────────────────
#
# This is M1 from the DR plan, and it is the single change that moves the
# recovery point: worst-case data loss goes from 24 hours to 4. Everything else
# delivered in 2026 improved recovery TIME; none of it touched this, because
# recovery point is set purely by how often data leaves the machine.
#
# Snapshots are incremental — only changed blocks are stored — so six per day
# costs far less than six times the storage. Retention also rises 14 -> 30 days,
# which closes G11.
#
# ── IT IS ALSO WHAT MAKES BACKUP ALERTING POSSIBLE ───────────────────────────
#
# Cloud Monitoring refuses an absence condition longer than 23h30m. Against a
# DAILY schedule that is unusable: consecutive snapshots are already 24h apart,
# so any alert able to detect a stopped schedule also fires shortly before every
# healthy one. Verified the hard way — the API rejected a 26h window outright,
# and the four most recent daily snapshots were spaced 24h apart to within a
# second, so there was no slack to exploit.
#
# At four-hourly the gap is 4h, an absence window of ~5h is comfortable, and
# `google_monitoring_alert_policy.snapshots_stopped` in monitoring.tf becomes a
# real control rather than a daily false alarm.
#
# ── WHY A NEW POLICY RATHER THAN AN EDIT ─────────────────────────────────────
#
# A resource policy's schedule cannot be changed in place; Terraform must
# destroy and recreate it. A disk also accepts only ONE snapshot schedule, so
# the attachment has to be swapped rather than doubled up.
#
# The old policy is therefore left DEFINED and simply detached, instead of being
# deleted in the same change. If anything about the new schedule misbehaves,
# re-attaching the previous one is a one-line revert against a policy that still
# exists, rather than a rebuild under pressure. It is removed in a follow-up once
# the new schedule has been observed producing snapshots.
resource "google_compute_resource_policy" "prod_4h" {
  name    = "odoo-prod-4h"
  project = var.project_id
  region  = var.region

  snapshot_schedule_policy {
    # NO snapshot_properties block here, deliberately — and note that the older
    # daily policy below DOES have one. They are not inconsistent.
    #
    # That policy was IMPORTED, and the live resource carried an empty
    # snapshot_properties block, so omitting it there plans a change forever.
    # This policy was CREATED by Terraform, and GCP does not persist the block at
    # all when every value inside it is the default — so declaring it here plans
    # a change forever in the opposite direction. The first plan after creating
    # this caught exactly that: a permanent one-line diff adding
    # `guest_flush = false` back.
    #
    # guest_flush defaults to false regardless, so nothing is lost. Snapshots
    # stay crash-consistent, which is gap G3 in the DR plan and is addressed
    # there by application-consistent logical dumps, not by this flag — enabling
    # guest_flush requires a VSS-style guest agent that this Linux host does not
    # run.
    #
    # A plan that is never empty is worse than a cosmetic annoyance: it trains
    # whoever runs it to skim, and the empty-plan gate is the only thing that
    # caught three unintended production destroys during the Phase 1 import.

    schedule {
      hourly_schedule {
        hours_in_cycle = 4
        # 01:00 UTC, deliberately offset from the old 13:00 slot so the first
        # new snapshot is visibly distinguishable from the last old one.
        start_time = "01:00"
      }
    }

    retention_policy {
      max_retention_days    = 30
      on_source_disk_delete = "KEEP_AUTO_SNAPSHOTS"
    }
  }
}

# ── Previous daily schedule — RETAINED, DETACHED ───────────────────────────────
# Superseded by prod_4h above. Kept defined but no longer attached to any disk,
# as the rollback path described there. Delete once the 4-hourly schedule has
# been confirmed producing snapshots on its own cadence.
#
# The snapshots it already took are unaffected: on_source_disk_delete is
# KEEP_AUTO_SNAPSHOTS, and detaching a policy never deletes existing snapshots.

resource "google_compute_resource_policy" "daily_snapshot" {
  name    = "default-schedule-1"
  project = var.project_id
  region  = var.region

  snapshot_schedule_policy {
    # Present on the live policy as an empty block. Omitting it plans a change.
    snapshot_properties {
      guest_flush       = false
      labels            = {}
      storage_locations = []
    }

    schedule {
      daily_schedule {
        days_in_cycle = 1
        start_time    = "13:00"
      }
    }

    retention_policy {
      max_retention_days    = 14
      on_source_disk_delete = "KEEP_AUTO_SNAPSHOTS"
    }
  }
}

# ── Production instance ────────────────────────────────────────────────────────

resource "google_compute_instance" "prod" {
  name         = "odoo-19-prod"
  project      = var.project_id
  zone         = var.prod_zone
  machine_type = var.prod_machine_type

  # Already enabled before this module existed. Terraform respects it: an apply
  # that would delete this instance fails instead, which is the intent.
  deletion_protection = true
  description         = "Odoo 19 Production Server - Created Dec 2025"

  tags = ["http-server", "https-server"]

  # No `labels` block on purpose. The VM carries goog-ops-agent-policy, but that
  # is applied by the OS Config agent policy and surfaces in effective_labels,
  # not in Terraform-managed labels — which the import read as empty. Declaring
  # it here would make Terraform claim ownership of a label it does not control
  # and fight the policy that sets it.

  metadata = {
    # Set by the Ops Agent policy. Omitting it plans its REMOVAL, which would
    # quietly detach the VM from that policy.
    enable-osconfig = "TRUE"

    # ── OS Login ────────────────────────────────────────────────────────────
    # Enabled at the INSTANCE level, not project-wide, so the blast radius is
    # one VM.
    #
    # This is a HARD CUTOVER. The moment it is on, the six never-expiring SSH
    # keys in project metadata stop working on this machine. Anyone relying on
    # them loses access until granted roles/compute.osLogin or osAdminLogin.
    #
    # It was brought forward from Phase 4 because the deploy pipeline needs it.
    # Without OS Login, `gcloud compute ssh` falls back to writing an ephemeral
    # key into instance metadata, which needs compute.instances.setMetadata —
    # a permission the build service account does not have, and must not be
    # given: setMetadata permits writing `startup-script`, which runs as ROOT
    # at next boot. Granting it would hand permanent root on production to
    # anything that can trigger a build. OS Login is both the correct fix and
    # the more restrictive one.
    #
    # Verified before enabling: tech@ holds compute.instances.osAdminLogin and
    # osLogin (tested via testIamPermissions, not assumed), so administrative
    # access survives the flip. Serial console remains as a backstop.
    enable-oslogin = "TRUE"
  }

  boot_disk {
    source      = google_compute_disk.prod.id
    auto_delete = false
    device_name = "odoo-19-prod"
  }

  network_interface {
    network    = "default"
    subnetwork = "default"
    stack_type = "IPV4_ONLY"

    access_config {
      nat_ip       = google_compute_address.prod.address
      network_tier = "PREMIUM"
    }
  }

  # ── The service account swap happens HERE, and only while stopped ───────────
  #
  # Today: odoo-bq-access@, which holds four BigQuery roles and NOTHING else.
  # That is genuine least privilege, but it has a live consequence: the Ops Agent
  # is installed and active on this VM and has been silently dropping every
  # metric and log it collects, because the account cannot call
  # monitoring.timeSeries.create. Verified in the agent's own journal —
  # "PermissionDenied", 1121 items dropped in a single batch.
  #
  # Which means there is currently NO possible alert on the disk, and the disk is
  # 82% full.
  #
  # odoo-prod-vm@ already holds logging.logWriter, monitoring.metricWriter and
  # artifactregistry.reader, so pointing this at it fixes observability as a side
  # effect of the Phase 4 swap.
  #
  # CHANGING THIS FIELD REQUIRES THE INSTANCE TO BE STOPPED. Terraform will do
  # that automatically — which is exactly why it must only be applied inside the
  # maintenance window, bundled with the machine type change so the VM stops once
  # rather than twice.
  service_account {
    # SWAPPED IN PHASE 4C. Previously odoo-bq-access@.
    #
    # Verified permission-neutral BEFORE the swap, role by role, in BOTH
    # projects — odoo-prod-vm@ holds a strict superset:
    #   odoo-472708:       old 5 roles, new 7 — missing: none
    #   cleardeals-459513: old 4 roles, new 4 — missing: none
    #
    # That mattered more than the plan assumed. BigQuery is not dead: 22 files
    # across lead_suggestor and leads/models/lead_score.py use it, and the data
    # lives in cleardeals-459513, a different project, where odoo-prod-vm@ had
    # no access at all. Attaching it without those grants would have broken lead
    # scoring at runtime with no startup error and no failed health check.
    #
    # What this account adds over the old one: logging.logWriter and
    # monitoring.metricWriter. The Ops Agent has been installed and running on
    # this VM for months, silently dropping every metric and log because
    # odoo-bq-access@ cannot call monitoring.timeSeries.create. This swap is
    # what finally makes VM memory and DISK metrics exist — and therefore what
    # makes a disk-full alert possible at all.
    #
    # CHANGING THIS FIELD REQUIRES A STOPPED INSTANCE. Terraform will stop,
    # change and restart the VM, so only ever apply it inside an agreed window,
    # bundled with the machine type so the VM stops once rather than twice.
    email  = google_service_account.prod_vm.email
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }

  scheduling {
    automatic_restart   = true
    on_host_maintenance = "MIGRATE"
    preemptible         = false
    provisioning_model  = "STANDARD"
  }

  shielded_instance_config {
    enable_secure_boot          = false
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  # Live value is "NONE". Omitting it makes the provider plan a change to null,
  # and this field FORCES REPLACEMENT — the first plan wanted to destroy and
  # recreate production over an attribute nobody set on purpose.
  key_revocation_action_type = "NONE"

  allow_stopping_for_update = true

  lifecycle {
    # ssh-keys metadata is REWRITTEN CONTINUOUSLY by whoever runs
    # `gcloud compute ssh` — the value observed during this import changed within
    # the hour, from cdgcphub keys to a solutionanalysts pair stamped minutes
    # earlier. Terraform must not fight that churn, and must never be the thing
    # that revokes someone's access mid-session.
    #
    # The churn is itself the argument for OS Login: after that cutover this
    # field stops moving, because access stops living in metadata at all.
    ignore_changes = [metadata["ssh-keys"]]
  }
}

# ── Staging instance ───────────────────────────────────────────────────────────
# Imported for completeness: it shares this project and every firewall rule
# below, so leaving it unmanaged means the rules cannot be reasoned about.
# NOTE it runs the WhatsApp half of Odoo and is the CURRENT production push
# target for the platform — despite the name.

resource "google_compute_instance" "stage" {
  name         = "odoo-stage"
  project      = var.project_id
  zone         = var.stage_zone
  machine_type = "e2-medium"

  tags = ["odoo-stage"]

  # Matches what is actually attached. Both fields were guessed initially and
  # both force replacement when wrong.
  #
  # NOTE auto_delete is TRUE here, unlike prod: deleting the staging instance
  # DESTROYS its 40 GB disk with it. Left as-is because changing it is a real
  # change to production infrastructure, not an import fix — but it is worth
  # fixing deliberately later.
  boot_disk {
    source      = "https://www.googleapis.com/compute/v1/projects/${var.project_id}/zones/${var.stage_zone}/disks/odoo-stage"
    auto_delete = true
    device_name = "persistent-disk-0"
  }

  network_interface {
    network    = "default"
    subnetwork = "default"
    stack_type = "IPV4_ONLY"

    access_config {
      nat_ip       = google_compute_address.stage.address
      network_tier = "PREMIUM"
    }
  }

  service_account {
    email  = "odoo-stage-vm@${var.project_id}.iam.gserviceaccount.com"
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }

  allow_stopping_for_update = true

  lifecycle {
    ignore_changes = [metadata["ssh-keys"], metadata["startup-script"]]
  }
}
