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
  name    = google_compute_resource_policy.daily_snapshot.name
  disk    = google_compute_disk.prod.name
  project = var.project_id
  zone    = var.prod_zone
}

# ── Snapshot schedule ──────────────────────────────────────────────────────────
# Pre-existing, and the reason a month of dated snapshots exists. Imported rather
# than recreated: recreating it would detach and reattach the policy on a live
# production disk for no gain.

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
    email  = "odoo-bq-access@${var.project_id}.iam.gserviceaccount.com"
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
