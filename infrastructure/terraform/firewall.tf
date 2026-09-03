# infrastructure/terraform/firewall.tf
#
# Phase 5 has removed the dangerous rules. What each deletion was, and the
# evidence gathered before removing it, is recorded below in place of the
# resource, so the history stays with the file rather than in a chat log.
#
# The imports in Phase 1 deliberately captured every rule EXACTLY as it was,
# including the broken ones. That separation is what made this diff reviewable:
# the import proved what production actually looked like, and only then did
# anything change. Fixing a rule during an import is how an import turns into an
# outage.

# ── DELETED in Phase 5 ─────────────────────────────────────────────────────────
#
# allow-postgres-from-script — tcp:5432 from 0.0.0.0/0, NO target tags, so it
#   applied to every VM in the project, present and future. Verified before
#   deleting: the db service publishes no host port (it listens only on the
#   internal compose bridge), and a connection from outside was refused by the
#   host rather than dropped by the firewall — which is the proof that the rule
#   really was permitting the traffic and only the absent listener stood in the
#   way. An armed trap, not a live breach: the next container to add a `ports:`
#   line would have been world-open with no firewall change for anyone to review.
#
# default-allow-rdp — tcp:3389 from 0.0.0.0/0. Nothing in this project runs
#   Windows and nothing listens on 3389.
#
# allow-odoo-web-traffic — tcp:80,443,8069 from 0.0.0.0/0, untagged. Deleted
#   outright rather than narrowed, because it was fully redundant: every VM in
#   the project already receives its web traffic through a TAGGED rule
#   (default-allow-http / default-allow-https for the production instance,
#   odoo-stage-web for staging), and those tags are managed in compute.tf, so
#   they cannot drift away underneath this. Port 8069 was never reachable in the
#   first place — Traefik terminates TLS and proxies to Odoo over the internal
#   network — so the port was open in the firewall and closed on the host, which
#   is misleading rather than harmful. A rule that grants nothing is worse than
#   useless: it is read as load-bearing by the next person to touch it.

# default-allow-ssh — DELETED in Phase 5. tcp:22 from 0.0.0.0/0 at the default
# priority, untagged. Superseded entirely by allow-iap-ssh below.

# ── The only remaining way in ──────────────────────────────────────────────────
#
# This rule used to be a fiction. The name said IAP, but alongside the real IAP
# range it also listed 0.0.0.0/0 — which made the IAP entry decorative and the
# rule exactly equivalent to "SSH from anywhere". Deleting default-allow-ssh
# while this still said 0.0.0.0/0 would have hardened nothing.
#
# 35.235.240.0/20 is Google's fixed IAP TCP-forwarding range, and it is the
# whole point: SSH is no longer reachable from the internet at all. Every
# connection is brokered by IAP, which authenticates the caller against IAM
# BEFORE a packet reaches sshd, and logs it. Combined with OS Login on the
# instances (see compute.tf), access is granted and revoked purely through IAM
# — there is no key on the host to forget to remove when someone leaves.
#
# ── Before narrowing this, BOTH callers were proven to work through IAP ────────
#
#   * Cloud Build — cloudbuild.yaml already deploys with --tunnel-through-iap,
#     and had been doing so successfully for every deploy in Phase 4.
#   * The operator — verified interactively over the tunnel under OS Login.
#
# That order matters. The auth log showed real, recent, successful logins
# arriving DIRECTLY on the public address under the legacy instance-metadata
# key, not through the tunnel. Removing the world-open rules without first
# proving the tunnel would have cut the only path anyone was actually using.
#
# ── Day-to-day consequence ────────────────────────────────────────────────────
#
# Plain `ssh <public-ip>` no longer connects, by design. Use:
#
#   gcloud compute ssh <instance> --zone=<zone> --tunnel-through-iap
#
# ── If this ever locks everyone out ───────────────────────────────────────────
#
# It is recoverable without SSH, and that was confirmed rather than assumed
# before this change: firewall rules are Compute API calls, so a replacement
# rule can be recreated from any authenticated machine in well under a minute.
# Losing SSH here does not mean losing the instance.
resource "google_compute_firewall" "allow_iap_ssh" {
  name        = "allow-iap-ssh"
  project     = var.project_id
  network     = "default"
  description = "Allow IAP SSH access"

  direction     = "INGRESS"
  priority      = 1000
  source_ranges = ["35.235.240.0/20"]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

# ── Rules that are correct and stay ────────────────────────────────────────────
#
# The two default-allow-* rules below are what actually serves production, via
# the http-server / https-server tags on the instance in compute.tf. Deleting
# allow-odoo-web-traffic was therefore a no-op for reachability — but only
# because of those tags, so do not remove them without revisiting this file.

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
