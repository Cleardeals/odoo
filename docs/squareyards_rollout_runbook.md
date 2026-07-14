# Square Yards Integration — Rollout & Verification Runbook

Internal runbook for deploying the Square Yards portal integration and the
accompanying legacy-column cleanup. Work through it top to bottom.

Branch: `feature/squareyards-integration`

---

## 0. What's in this changeset

| Area | Modules | Migration? |
|---|---|---|
| Square Yards portal on properties (Story 1) | `properties` | No (additive) |
| Square Yards lead source + config (Story 2) | `leads` | No (data + version bump) |
| Authenticated webhook `POST /api/v1/squareyards_webhook` (Story 3) | `leads` | No |
| Legacy `property.listing.id_*` field removal (Tier 1) | `property_listings` | No (module not installed) |
| Retire `property.base` legacy portal columns (Tier 2) | `properties`, `leads` | **Yes — drops columns** |

The Tier 2 column drop is the only step with real data risk. Treat it with the
staging rehearsal in Section 2.

---

## 1. Pre-deploy checks

- [ ] Tests green: `./run_tests.sh leads properties` → 0 failed, 0 errors.
- [ ] Manifest versions bumped: `properties` = `19.0.1.5.0`, `leads` = `1.7.0`.
- [ ] Pre-push review clean (run the `odoo-pre-push-review` skill over the diff)
      — manifest/version/access/view/migration checks.
- [ ] Confirm the Square Yards `lead.source` seed points at a real fallback RM
      user ("Purvi Desai") in the target DB, or a manager will set it post-deploy.

---

## 2. Tier 2 migration — staging rehearsal (do this FIRST)

The `19.0.1.5.0` migration drops four columns from `property_base`
(`ninety_nine_acres_id`, `housing_id`, `magicbricks_id`, `olx_id`). It is
idempotent and lossless (it re-runs the backfill into `property_portal_listing`
before dropping), but rehearse on real data before prod:

1. Restore a **fresh production snapshot** onto staging.
2. Upgrade the `properties` module on staging so the migration runs.
3. In the logs, read the **safety-net backfill counts**, e.g.:
   ```
   property_base.ninety_nine_acres_id: safety-net backfilled N portal listing row(s) before drop.
   ```
   - **All `N = 0`** → every legacy ID was already mirrored into
     `property.portal.listing`. The drop is provably lossless. Proceed to prod.
   - **Any `N > 0`** → those legacy IDs were not yet in the new model; the net
     rescued them. A small number is fine. A large/surprising number → stop and
     investigate why data bypassed `property.portal.listing` before trusting prod.
4. Sanity check on staging: existing portal-based lead matching still works, and
   property forms load (no reference to dropped columns).

---

## 3. Production deploy

1. Deploy the branch and upgrade both modules (`-u properties,leads`).
2. Watch the migration log again for the backfill counts (expect all 0 after the
   staging rehearsal).
3. **Set the webhook API key** (the endpoint returns `503` until this is set):
   - Settings → Technical → System Parameters
   - Key: `squareyards.webhook.api.key`
   - Value: a strong shared secret.
4. Confirm the Square Yards `lead.source` has a **Fallback RM** set
   (Leads → Lead Operations → Settings → Sources → SquareYards).

---

## 4. Share with the Square Yards team

- [ ] Send `docs/squareyards_webhook_integration.md`.
- [ ] Provide the production endpoint URL (`https://<PROD_HOST>/api/v1/squareyards_webhook`).
- [ ] Deliver the `apikey` secret out-of-band (not in the doc / not over email in plain text).
- [ ] Fill in the doc's Section 9 contact + change-log date.

---

## 5. Live smoke test (staging or a controlled prod check)

Register at least one real property with a SquareYards listing, then run the
Postman collection (`postman/`) or these manual checks:

1. **Matched:** POST a lead with `propertyId` = a registered SquareYards listing.
   - Expect `200`. In Odoo: a new `leads.new` with `property_base_id` set and
     assigned to that property's RM.
2. **Unmatched:** POST with an unregistered `propertyId`.
   - Expect `200`. Lead has no property link and is assigned to the fallback RM.
3. **Duplicate:** re-POST the matched lead.
   - Expect `200`. No second lead is created.
4. **WhatsApp flow:** POST with only `mobile` + `propertyId`.
   - Expect `200`. Lead name is `SquareYards Lead`.
5. **Auth:** POST with a wrong `apikey` → `401`; with no key set on the server → `503`.

---

## 6. Rollback notes

- Code/config (Stories 1–3, Tier 1) roll back cleanly by redeploying the previous
  revision — they are additive.
- The Tier 2 **column drop cannot be un-dropped by a code rollback** (the columns
  are gone from the DB). This is safe because the data lives in
  `property.portal.listing` and nothing reads the old columns anymore. If a
  rollback to pre-Tier-2 code is ever required, that older code simply no longer
  references those columns via the ORM — but do **not** expect the physical
  columns to reappear. This is why the staging rehearsal in Section 2 is
  mandatory before prod.

---

## 7. Post-deploy monitoring

- Watch server logs for `SquareYards Webhook` entries: `401`/`503` spikes signal a
  key mismatch or unset parameter; `Exception` entries need investigation.
- Confirm the first real Square Yards leads land with the correct RM assignment.
