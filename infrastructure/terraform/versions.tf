# infrastructure/terraform/versions.tf
#
# State lives in a bucket in THIS project, not in the WhatsApp platform's
# cleardeals-tf-state. Sharing that bucket would have tied Odoo's state to the
# lifecycle and IAM of an unrelated project, and forced a cross-project grant for
# the Odoo CI service account. A project-level mistake should stop at that project.
#
# The bucket has uniform bucket-level access, public access prevention, and object
# versioning, so a truncated state write is recoverable from a prior generation.

terraform {
  required_version = ">= 1.5.0"

  backend "gcs" {
    bucket = "cleardeals-odoo-tfstate"
    prefix = "odoo-prod"
  }

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
