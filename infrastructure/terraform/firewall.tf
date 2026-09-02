# infrastructure/terraform/firewall.tf
#
# All ten rules as they exist TODAY. Several are wrong, and three are dangerous.
# They are imported unchanged and as-is on purpose: the point of this module is
# first to make the current state visible and reviewable, and only then to change
# it. Fixing a rule during an import is how an import turns into an outage.
#
# The corrections belong to Phase 5 and are marked PHASE 5 below, so the diff
# that removes them is small, obvious and reviewable on its own.

# ── Rules that should be DELETED in Phase 5 ────────────────────────────────────

# PHASE 5 — DELETE. This is the worst rule in the project.
#
# tcp:5432 open to the entire internet with NO target tags, so it applies to
# every VM in the project, present and future.
#
# Nothing is exposed *today* only because the db service in docker-compose.yml
# publishes no ports — Postgres listens on the internal bridge network. So this
# is an armed trap rather than a live breach: the next VM that publishes 5432 is
# world-open the moment it boots, with no firewall change for anyone to review.
#
# It matters more than that sounds, because POSTGRES_PASSWORD=odoo is committed
# in this PUBLIC repository. The weak password and this rule are each survivable
# alone. Together they are one `ports:` line away from total compromise.
resource "google_compute_firewall" "allow_postgres_from_script" {
  name        = "allow-postgres-from-script"
  project     = var.project_id
  network     = "default"
  description = "Allows our active-to-active script to access odoo postgres database"

  direction     = "INGRESS"
  priority      = 1000
  source_ranges = ["0.0.0.0/0"]

  allow {
    protocol = "tcp"
    ports    = ["5432"]
  }
}

# PHASE 5 — DELETE. Port 22 open to the world at the default priority.
# Superseded by allow-iap-ssh once that is corrected below.
resource "google_compute_firewall" "default_allow_ssh" {
  name        = "default-allow-ssh"
  project     = var.project_id
  network     = "default"
  description = "Allow SSH from anywhere"

  direction     = "INGRESS"
  priority      = 65534
  source_ranges = ["0.0.0.0/0"]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

# PHASE 5 — DELETE. Nothing in this project runs Windows.
resource "google_compute_firewall" "default_allow_rdp" {
  name        = "default-allow-rdp"
  project     = var.project_id
  network     = "default"
  description = "Allow RDP from anywhere"

  direction     = "INGRESS"
  priority      = 65534
  source_ranges = ["0.0.0.0/0"]

  allow {
    protocol = "tcp"
    ports    = ["3389"]
  }
}

# ── Rules that should be NARROWED in Phase 5 ───────────────────────────────────

# PHASE 5 — FIX THE SOURCE RANGES.
#
# The name says IAP. The rule does not: alongside the real IAP range
# 35.235.240.0/20 it also lists 0.0.0.0/0, which makes the IAP entry decorative
# and the rule equivalent to "SSH from anywhere".
#
# Drop 0.0.0.0/0 and SSH arrives only through IAP — but ONLY after the OS Login
# cutover is proven working, or you remove the path you are standing on.
resource "google_compute_firewall" "allow_iap_ssh" {
  name        = "allow-iap-ssh"
  project     = var.project_id
  network     = "default"
  description = "Allow IAP SSH access"

  direction     = "INGRESS"
  priority      = 1000
  source_ranges = ["35.235.240.0/20", "0.0.0.0/0"] # PHASE 5: drop 0.0.0.0/0

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

# PHASE 5 — SCOPE TO A TAG AND DROP 8069.
# Untagged, so it applies to every VM. 8069 is not published by compose at all —
# Traefik terminates TLS and proxies internally — so the port is open in the
# firewall and closed on the host, which is misleading rather than harmful.
resource "google_compute_firewall" "allow_odoo_web_traffic" {
  name        = "allow-odoo-web-traffic"
  project     = var.project_id
  network     = "default"
  description = "Ensure web traffic can reach the odoo vm"

  direction     = "INGRESS"
  priority      = 1000
  source_ranges = ["0.0.0.0/0"]

  allow {
    protocol = "tcp"
    ports    = ["80", "443", "8069"] # PHASE 5: drop 8069, add target_tags
  }
}

# ── Rules that are correct and stay ────────────────────────────────────────────

resource "google_compute_firewall" "default_allow_http" {
  name    = "default-allow-http"
  project = var.project_id
  network = "default"

  direction     = "INGRESS"
  priority      = 1000
  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["http-server"]

  allow {
    protocol = "tcp"
    ports    = ["80"]
  }
}

resource "google_compute_firewall" "default_allow_https" {
  name    = "default-allow-https"
  project = var.project_id
  network = "default"

  direction     = "INGRESS"
  priority      = 1000
  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["https-server"]

  allow {
    protocol = "tcp"
    ports    = ["443"]
  }
}

resource "google_compute_firewall" "odoo_stage_web" {
  name    = "odoo-stage-web"
  project = var.project_id
  network = "default"

  direction     = "INGRESS"
  priority      = 1000
  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["odoo-stage"]

  allow {
    protocol = "tcp"
    ports    = ["80"]
  }

  allow {
    protocol = "tcp"
    ports    = ["443"]
  }
}

resource "google_compute_firewall" "default_allow_icmp" {
  name        = "default-allow-icmp"
  project     = var.project_id
  network     = "default"
  description = "Allow ICMP from anywhere"

  direction     = "INGRESS"
  priority      = 65534
  source_ranges = ["0.0.0.0/0"]

  allow {
    protocol = "icmp"
  }
}

resource "google_compute_firewall" "default_allow_internal" {
  name        = "default-allow-internal"
  project     = var.project_id
  network     = "default"
  description = "Allow internal traffic on the default network"

  direction     = "INGRESS"
  priority      = 65534
  source_ranges = ["10.128.0.0/9"]

  allow {
    protocol = "tcp"
    ports    = ["0-65535"]
  }

  allow {
    protocol = "udp"
    ports    = ["0-65535"]
  }

  allow {
    protocol = "icmp"
  }
}
