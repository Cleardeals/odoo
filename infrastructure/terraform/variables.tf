# infrastructure/terraform/variables.tf

variable "project_id" {
  type        = string
  description = "GCP project ID hosting both Odoo VMs"
  # No default — supplied via terraform.tfvars (gitignored). This repo is public.
}

variable "region" {
  type        = string
  description = "Default region for regional resources"
  default     = "us-central1"
}

# The two VMs are in DIFFERENT zones. This is not a mistake to be tidied up:
# moving a zonal VM means recreating it, so the zones are recorded as they are.
variable "prod_zone" {
  type        = string
  description = "Zone of odoo-19-prod"
  default     = "us-central1-f"
}

variable "stage_zone" {
  type        = string
  description = "Zone of odoo-stage"
  default     = "us-central1-c"
}

variable "prod_machine_type" {
  type        = string
  description = <<-EOT
    Machine type for odoo-19-prod.

    Currently e2-medium: 2 SHARED vCPUs and 4 GB, running Odoo in threaded mode
    (workers = 0, a single process). The Phase 4 target is e2-standard-2 —
    dedicated cores and 8 GB — which is what makes prefork viable.

    Changing this REQUIRES THE INSTANCE TO BE STOPPED. Terraform will stop it,
    change it, and start it again, so never apply a change to this value outside
    an agreed maintenance window.
  EOT
  default     = "e2-medium"
}

variable "prod_boot_disk_size_gb" {
  type        = number
  description = <<-EOT
    Boot disk size for odoo-19-prod.

    30 GB today and 82% FULL — 5.3 GB free, with Docker (8.7 GB), the Postgres
    data directory (2.8 GB), the git checkout (980 MB) and the filestore (172 MB)
    all sharing it. The Phase 4 target is 60.

    Growing a disk is safe and online. SHRINKING IS IMPOSSIBLE — lowering this
    number produces an apply error, not a smaller disk.
  EOT
  default     = 30
}
