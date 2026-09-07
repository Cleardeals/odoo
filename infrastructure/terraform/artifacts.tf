# infrastructure/terraform/artifacts.tf
# Images move OFF the VM. Today `docker compose build` runs on the production
# host, competing with Odoo for the CPU and the disk that is already 82% full.

resource "google_artifact_registry_repository" "odoo" {
  repository_id = "odoo"
  project       = var.project_id
  location      = var.region
  format        = "DOCKER"
  description   = "Odoo production images, tagged by commit SHA"
}
