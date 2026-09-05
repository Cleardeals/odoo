# infrastructure/terraform/monitoring.tf
#
# Phase 6 — alerting. Before this file there was NOTHING: zero alert policies,
# zero notification channels, zero uptime checks in the project. Production Odoo
# ran unwatched, and every incident so far has been found by a person looking at
# the site.
#
# This was blocked until Phase 4c, and not for the reason it looked like. The
# Ops Agent had been installed and running for months while shipping nothing at
# all — it lacked monitoring.timeSeries.create and was dropping every batch it
# collected. Alerting on metrics that were never arriving would have produced a
# dashboard of flat lines and a false sense of coverage. The service-account
# swap in 4c fixed the permission; these policies are the point of having done
# it.
#
# ── THRESHOLDS ARE VALIDATED AGAINST REAL DATA, NOT ASSUMED ───────────────────
#
# Every threshold below was checked against the metrics this project is actually
# producing. That check changed two of them, and would have shipped two alerts
# that fire permanently on day one:
#
#   * disk/percent_used has ELEVEN series on this host, and eight of them sit at
#     exactly 100% forever. They are /dev/loopN — snap squashfs mounts, which
#     are read-only and full by definition. A plain "disk > 85%" alert fires
#     immediately, on eight series, and never clears.
#
#   * cpu/utilization is reported PER STATE, and the largest series is `idle`,
#     sitting at ~96% on a healthy idle box. A plain "cpu > 85%" alert fires
#     continuously precisely when nothing is wrong.
#
# An alert that is always firing is worse than no alert. It is not neutral: it
# teaches everyone to close the notification without reading it, and the one
# that matters arrives in a mailbox where alerts have already been reclassified
# as noise.

# ── Where alerts go ────────────────────────────────────────────────────────────
#
# GCP sends a verification email when this channel is created, and the channel
# DELIVERS NOTHING until somebody clicks the link in it. A policy attached to an
# unverified channel looks completely healthy in the console and silently pages
# no one, which is the worst possible failure mode for the thing whose entire
# job is to tell you about failure.
resource "google_monitoring_notification_channel" "email" {
  project      = var.project_id
  display_name = "Odoo production alerts"
  type         = "email"

  labels = {
    email_address = var.alert_email
  }
}

locals {
  alert_prefix   = "[odoo-prod]"
  alert_channels = [google_monitoring_notification_channel.email.id]
}

# ── P1: the site is unreachable from the internet ─────────────────────────────
#
# The single highest-value alert here, because it is the only one that asks the
# question a user asks. It is indifferent to WHICH layer broke: it catches the
# VM being down, Odoo being down, Postgres being unreachable, an expired
# certificate, and — the one that motivated it — Traefik alive but routing
# nothing.
#
# That last case is not hypothetical. In the Phase 4c window Traefik's docker
# provider died on a client/daemon API mismatch, so it discovered no containers
# and served 404 for every request while Odoo sat behind it perfectly healthy.
# Every internal check passed. An external check is the only thing that sees it.
#
# scripts/deploy.sh now runs the same assertion, but ONLY during a deploy. This
# watches the other 99% of the time, when nobody is looking.
resource "google_monitoring_uptime_check_config" "site" {
  project      = var.project_id
  display_name = "Odoo production — /web/login"
  timeout      = "10s"
  period       = "300s"

  http_check {
    path           = "/web/login"
    port           = 443
    use_ssl        = true
    request_method = "GET"

    # validate_ssl makes a certificate problem FAIL the check rather than being
    # silently ignored. Traefik renews via ACME on its own, and the renewal
    # notices go to a personal mailbox outside the company — so a failed renewal
    # has no other route to anybody's attention.
    validate_ssl = true

    accepted_response_status_codes {
      status_class = "STATUS_CLASS_2XX"
    }
  }

  # /web/login is chosen over / deliberately. The root path redirects, and a
  # redirect is served by Traefik's entrypoint BEFORE any routing happens — so a
  # check against / passes even when no router exists, which is exactly the 4c
  # outage. Verified directly: with a hostname matching no router, port 80
  # returns 301 while the TLS path returns 404.
  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = var.public_host
    }
  }
}

resource "google_monitoring_alert_policy" "site_down" {
  project      = var.project_id
  display_name = "${local.alert_prefix} P1 Site unreachable from the internet"
  combiner     = "OR"

  documentation {
    content   = <<-EOT
      ${var.public_host}/web/login is not returning 2xx to Google's external
      uptime checkers.

      This alert is deliberately layer-agnostic — it says users cannot reach the
      site, not which component failed. Work outwards:

        1. Is the instance running?
        2. Is Odoo healthy from inside its own container?
             docker compose exec -T odoo curl -fsS \
               "http://localhost:8069/web/health?db_server_status=1"
        3. If Odoo is healthy but the site is not, it is the proxy or the
           routing. Check how many routers Traefik knows about:
             curl -s http://127.0.0.1:8080/api/rawdata | python3 -c \
               'import json,sys; print(len(json.load(sys.stdin)["routers"]))'
           ZERO ROUTERS is the signature of the Phase 4c failure: Traefik alive
           and answering, its docker provider dead, nothing routed anywhere.
        4. A certificate failure also trips this check, because validate_ssl is
           on. Traefik renews via ACME and the renewal notices go to a mailbox
           outside the company, so this alert may be the only warning.

      Access is through IAP now:
        gcloud compute ssh odoo-19-prod --project=<project> \
          --zone=us-central1-f --tunnel-through-iap
    EOT
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "uptime check failing from multiple regions"

    condition_threshold {
      filter = join(" AND ", [
        "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\"",
        "resource.type=\"uptime_url\"",
        "metric.label.check_id=\"${google_monitoring_uptime_check_config.site.uptime_check_id}\"",
      ])

      # REDUCE_COUNT_FALSE counts how many of Google's geographically separate
      # checkers are currently failing. Requiring more than one means a single
      # checker having a bad minute does not page anybody, while a real outage —
      # which every checker sees — still does. Alerting on a single failed check
      # produces false pages; alerting on all of them delays a real one.
      aggregations {
        alignment_period     = "1200s"
        per_series_aligner   = "ALIGN_NEXT_OLDER"
        cross_series_reducer = "REDUCE_COUNT_FALSE"
        group_by_fields      = ["resource.label.host"]
      }

      comparison      = "COMPARISON_GT"
      threshold_value = 1
      duration        = "60s"

      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.alert_channels

  alert_strategy {
    auto_close = "3600s"
  }
}

# ── P2: the root filesystem is filling ────────────────────────────────────────
#
# This has already nearly happened once. The disk was at 82% when Phase 4 began
# and was grown 30GB -> 60GB to relieve it. It is now back to ~62% and visibly
# climbing, because every deploy leaves another tagged image behind:
# `docker image prune -f` in scripts/deploy.sh removes DANGLING images only, and
# a tagged one is not dangling. Twelve images were resident when this was
# written, plus a 4.7GB .git left over from an accidental unshallow.
#
# A full disk on this host is not a degraded service, it is a stopped one:
# Postgres cannot write, Odoo cannot write, and the deploy that would fix it
# cannot pull an image.
#
# THE DEVICE FILTER IS LOad-BEARING. Without it this alert matches the eight
# /dev/loopN squashfs mounts that sit at 100% permanently. starts_with("/dev/sd")
# keeps the real block devices and excludes them, and is more durable than
# pinning /dev/sda1 by name.
resource "google_monitoring_alert_policy" "disk_filling" {
  project      = var.project_id
  display_name = "${local.alert_prefix} P2 Root filesystem above 85%"
  combiner     = "OR"

  documentation {
    content   = <<-EOT
      A real block device on an Odoo VM is over 85% full.

      A full disk here stops the service outright — Postgres cannot write, Odoo
      cannot write, and the deploy that would fix it cannot pull an image. Do
      not wait for it to resolve itself; it does not.

      Usual consumers, in the order they are usually guilty:

        docker system df               # accumulated deploy images
        du -sh /opt/odoo/.git          # ~4.7GB from an accidental unshallow
        du -sh /var/log                # container logs, capped at 50MB x 5 each

      Reclaiming space, least destructive first:

        docker image prune -a --filter "until=336h"   # untagged AND old tagged
        docker builder prune                          # build cache

      The disk can also be grown online with no downtime — this was done once
      already, 30GB -> 60GB, with growpart + resize2fs while the service stayed
      up. Growing it is the answer if usage is legitimate; pruning is the answer
      if it is accumulated deploy debris.
    EOT
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "disk used > 85% on a real block device"

    condition_threshold {
      filter = join(" AND ", [
        "metric.type=\"agent.googleapis.com/disk/percent_used\"",
        "resource.type=\"gce_instance\"",
        "metric.label.state=\"used\"",
        "metric.label.device=starts_with(\"/dev/sd\")",
      ])

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_MEAN"
      }

      comparison      = "COMPARISON_GT"
      threshold_value = 85

      # Five minutes, not instant. Disk usage is not spiky in a way that
      # self-corrects, so a sustained reading is the honest signal and this only
      # suppresses a transient blip during an image pull.
      duration = "300s"

      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.alert_channels

  alert_strategy {
    auto_close = "86400s"
  }
}

# ── P3: memory pressure ────────────────────────────────────────────────────────
#
# Measured at ~20% used with the prefork workers running, so 85% is a genuine
# anomaly rather than a number picked because it is round.
#
# Worth alerting on separately from the site check because Odoo's own worker
# recycling hides it for a while: limit_memory_hard kills and restarts a worker
# rather than letting it exhaust the host, so the site keeps answering while
# requests are being dropped underneath. The symptom is slowness, not an
# outage, and nothing else here would report it.
#
# NOTE those Odoo limits are VIRTUAL memory (RLIMIT_AS), which is why they read
# as enormous next to this metric: measured idle RSS is 141-182MB per worker
# against 663-727MB of VIRT. This alert watches the host's real memory. Do not
# reconcile the two numbers; they measure different things.
resource "google_monitoring_alert_policy" "memory_pressure" {
  project      = var.project_id
  display_name = "${local.alert_prefix} P3 Host memory above 85%"
  combiner     = "OR"

  documentation {
    content   = <<-EOT
      Host memory is above 85%. Baseline with the prefork workers running is
      about 20%, so this is a real change, not normal variation.

      Check for a worker leaking rather than assuming load:

        docker compose exec -T odoo ps -o pid,rss,vsz,etime,cmd -C odoo

      Odoo recycles a worker that exceeds limit_memory_hard, so the site may
      still be answering while requests are being dropped. Watch for repeated
      "virtual memory limit reached" in the Odoo logs — that is worker
      recycling, and it means the limits need review rather than the host.
    EOT
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "memory used > 85%"

    condition_threshold {
      filter = join(" AND ", [
        "metric.type=\"agent.googleapis.com/memory/percent_used\"",
        "resource.type=\"gce_instance\"",
        "metric.label.state=\"used\"",
      ])

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_MEAN"
      }

      comparison      = "COMPARISON_GT"
      threshold_value = 85
      duration        = "600s"

      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.alert_channels

  alert_strategy {
    auto_close = "86400s"
  }
}

# ── P4: the TLS certificate is close to expiring ──────────────────────────────
#
# Traefik renews via ACME automatically, so this should never fire. It exists
# because of where the failure notice would otherwise go: the ACME contact
# address on the resolver is a personal Gmail account, not a company mailbox. If
# renewal breaks, Let's Encrypt's warnings land somewhere nobody monitors, and
# the first anyone hears of it is the site failing.
#
# P1 already catches an EXPIRED certificate, because validate_ssl is on. This
# one is deliberately earlier: fifteen days is enough to debug an ACME problem
# calmly instead of during an outage.
resource "google_monitoring_alert_policy" "ssl_expiring" {
  project      = var.project_id
  display_name = "${local.alert_prefix} P4 TLS certificate expires in under 15 days"
  combiner     = "OR"

  documentation {
    content   = <<-EOT
      The certificate for ${var.public_host} expires in under 15 days and has
      not been renewed.

      Traefik renews automatically via ACME, so this firing means renewal is
      broken. It is a warning, not yet an outage — but it becomes an outage on a
      known date.

        docker compose logs traefik | grep -i acme

      The certificate lives in ./letsencrypt/acme.json on the VM. The tlsChallenge
      resolver needs port 80 reachable from the internet to complete a renewal,
      so confirm the firewall still permits it — default-allow-http covers this
      via the http-server tag on the instance.
    EOT
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "time until certificate expiry < 15 days"

    condition_threshold {
      filter = join(" AND ", [
        "metric.type=\"monitoring.googleapis.com/uptime_check/time_until_ssl_cert_expires\"",
        "resource.type=\"uptime_url\"",
        "metric.label.check_id=\"${google_monitoring_uptime_check_config.site.uptime_check_id}\"",
      ])

      aggregations {
        alignment_period   = "3600s"
        per_series_aligner = "ALIGN_MEAN"
      }

      comparison      = "COMPARISON_LT"
      threshold_value = 15
      duration        = "3600s"

      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.alert_channels

  alert_strategy {
    auto_close = "86400s"
  }
}
