# Multi Site Visit History: Implementation Design Decision Document

- Module: leads
- Last updated: 2026-03-30
- Status: Approved for implementation
- Scope: Leads inquiry records (`leads.new`) with multi-event site visit tracking

## 1. Decision Summary

This feature will keep `leads.new` as the inquiry model and introduce a dedicated visit-history model for site visits.

We are not creating a separate buyer inquiry model.

The new visit model will become the source of truth for all site visit lifecycle data. Existing single-slot legacy visit fields on inquiry records are transitional only and will be removed after production stabilization.

## 2. Business Context and Problem

Current behavior stores one site visit snapshot per inquiry (`site_visit_date` + status/feedback fields). This hides operational reality when a buyer:

1. Reschedules multiple times.
2. No-shows and comes back later.
3. Completes multiple visits before closure.

Management cannot quickly answer:

1. Why are visits not converting?
2. Which issues are property-driven vs RM process-driven?
3. How frequently does each inquiry reschedule?

## 3. Non-Goals

1. No new buyer inquiry master model.
2. No merge of historical duplicate phone+property inquiries.
3. No rewrite of lead assignment pipeline.
4. No temporary backward-compat API bridge (currently no external API consumers).

## 4. Core Architecture Decisions

### 4.1 Inquiry Identity

`leads.new` remains the inquiry identity record.

- `inquiry_type`: `primary` or `recommended`
- `parent_inquiry_id`: links recommended inquiry to parent primary inquiry

### 4.2 New Site Visit Event Model

Create `lead.site.visit` as append-only-ish event history for inquiry visits.

Each visit event stores:

1. Inquiry reference.
2. Property reference.
3. Scheduled datetime and computed date.
4. Status.
5. Status-specific feedback.
6. Notes.
7. Reschedule lineage metadata.

### 4.3 Status and Feedback Must Be Configurable

Statuses and feedback options must be UI-configurable by managers and not hardcoded Python selections.

Use metadata models:

1. `lead.site.visit.status`
2. `lead.site.visit.feedback.option`

Business records keep stable codes; labels and active behavior are configurable.

### 4.4 Recommended Property Flow Redesign

Replace inline recommended-properties editing with a popup wizard action from primary inquiry.

Wizard creates a new `leads.new` record with `inquiry_type='recommended'` and assigns selected property.

This new recommended inquiry is fully eligible for visit tracking in `lead.site.visit`.

### 4.5 Source of Truth Transition

Phase 1: dual-write/snapshot compatibility.

- New site visit events are canonical.
- Legacy inquiry fields may be updated from latest event for temporary continuity.

Phase 2: remove legacy fields after stabilization.

## 5. Data Model Design

## 5.1 `lead.site.visit.status`

Purpose: manager-managed status catalog.

Fields:

1. `name` (Char, required) manager-visible label
2. `code` (Char, required, unique, immutable) API/report key
3. `sequence` (Integer)
4. `active` (Boolean)
5. `is_terminal` (Boolean)
6. `counts_as_scheduled` (Boolean)
7. `counts_as_completed` (Boolean)
8. `counts_as_no_show` (Boolean)
9. `counts_as_cancelled` (Boolean)
10. `allow_reschedule_from` (Boolean)
11. `allow_feedback_note` (Boolean)
12. `color` (Integer) optional UI color index

Constraints:

1. Unique `code`.
2. `code` write-once after creation.

## 5.2 `lead.site.visit.feedback.option`

Purpose: manager-managed feedback options linked to status.

Fields:

1. `name` (Char, required)
2. `code` (Char, required, unique, immutable)
3. `status_id` (Many2one `lead.site.visit.status`, required)
4. `category` (Selection): `intent`, `blocker`, `property`, `pricing`, `operations`, `other`
5. `management_signal` (Selection): `positive_intent`, `risk`, `loss_reason`, `neutral`
6. `requires_note` (Boolean)
7. `sequence` (Integer)
8. `active` (Boolean)

Constraints:

1. Unique (`status_id`, `code`).
2. `code` write-once after creation.

## 5.3 `lead.site.visit`

Purpose: visit event rows for each inquiry.

Fields:

1. `inquiry_id` (Many2one `leads.new`, required, ondelete cascade)
2. `property_base_id` (Many2one `property.base`, required)
3. `assigned_rm_id` (Many2one `res.users`)
4. `inquiry_type` (related/store from inquiry)
5. `scheduled_datetime` (Datetime, required)
6. `scheduled_date` (Date, computed/store)
7. `status_id` (Many2one `lead.site.visit.status`, required)
8. `feedback_option_id` (Many2one `lead.site.visit.feedback.option`)
9. `feedback_note` (Text)
10. `previous_visit_id` (Many2one self)
11. `root_visit_id` (Many2one self)
12. `reschedule_iteration` (Integer, default 0)
13. `chain_reschedule_count` (Integer, computed)
14. `status_changed_on` (Datetime)
15. `active` (Boolean, default True)

Validation rules:

1. `feedback_option_id.status_id` must match `status_id`.
2. If status is configured as reschedule-type, `previous_visit_id` required.
3. `scheduled_datetime` required always.
4. If feedback option requires note, `feedback_note` required.

## 5.4 `leads.new` extensions

Add:

1. `inquiry_type` (Selection: `primary`, `recommended`, default `primary`)
2. `parent_inquiry_id` (Many2one `leads.new`)
3. `site_visit_ids` (One2many `lead.site.visit`)
4. `latest_site_visit_id` (Many2one `lead.site.visit`, computed/store)
5. optional helper counters (`site_visit_count`, `reschedule_count`)

Legacy visit fields retained only for transition.

## 6. Feedback Taxonomy (Baseline Seed)

Baseline status codes to seed (editable labels):

1. `scheduled`
2. `rescheduled`
3. `completed`
4. `cancelling`
5. `did_not_show_up`

Baseline feedback seed examples:

### scheduled

1. `buyer_confirmed_slot`
2. `buyer_tentative`
3. `awaiting_buyer_confirmation`
4. `owner_slot_confirmed`
5. `owner_slot_pending`
6. `access_or_key_pending`
7. `reminder_sent`
8. `other`

### rescheduled

1. `buyer_requested_time_change`
2. `owner_unavailable`
3. `rm_unavailable`
4. `property_access_issue`
5. `requirement_changed`
6. `traffic_or_distance_issue`
7. `documentation_pending`
8. `weather_or_emergency`
9. `other`

### cancelling

1. `buyer_cancelled_interest`
2. `owner_cancelled_availability`
3. `property_unavailable`
4. `duplicate_inquiry`
5. `invalid_contact`
6. `price_expectation_mismatch`
7. `location_mismatch`
8. `other`

### did_not_show_up

1. `buyer_no_show_unreachable`
2. `buyer_no_show_informed_late`
3. `owner_no_show`
4. `rm_no_show`
5. `access_denied`
6. `weather_or_emergency`
7. `other`

### completed

1. `high_intent_offer_expected`
2. `negotiation_started`
3. `second_visit_required`
4. `wants_more_options`
5. `rejected_price_high`
6. `rejected_location`
7. `rejected_property_condition`
8. `requirement_closed_elsewhere`
9. `deal_closed`
10. `other`

## 7. Security and Access Design

Groups:

1. Lead Manager: full CRUD for status, feedback-option, site-visit models.
2. Lead RM: create/read/write site visits only for owned inquiries. No unlink for site visits.

Rules:

1. RM can only create recommended inquiry from owned primary inquiry.
2. Config models visible/editable only to managers.

## 8. UX Design Decisions

### 8.1 Inquiry Form

1. Add visual banner: Primary Inquiry or Recommended Inquiry.
2. Add button: Add Site Visit (opens popup wizard).
3. Add button: Recommend Property (popup wizard; primary only).
4. Show site visit history one2many list with quick open form.

### 8.2 Site Visit Popup

1. Status dropdown from active status config.
2. Feedback options filtered by selected status.
3. Required-note behavior enforced by option config.
4. Reschedule flow auto-links previous visit.

## 9. API Migration Decision

All buyer/seller site visit APIs move to new model only.

Impacted endpoints:

1. `/api/track/lead/site-visits`
2. `/api/track/property/site-visits`
3. `/api/track/lead/activity` (visit counters)
4. `/api/track/property/activity` (visit fields)
5. `/api/track/property/funnel` (visit metrics)
6. `/api/track/property/portal-performance` (visit metrics)

No backward compatibility bridge required now.

## 10. Migration Strategy

### 10.1 Scope-limited backfill

Backfill only inquiries where current status is one of:

1. `site_visit_scheduled`
2. `site_visit_done`
3. `rescheduled`

Leave all other inquiries untouched.

### 10.2 Backfill behavior

1. Create one `lead.site.visit` event row from legacy fields where applicable.
2. Map old status/feedback values to new seeded status/feedback codes.
3. Set inquiry snapshots from latest event.

### 10.3 Post-stabilization cleanup

1. Remove legacy single-site-visit fields in follow-up release.

## 11. Implementation Phases

### Phase 1 (Foundation)

1. Add config models and views.
2. Add `lead.site.visit` model and core validations.
3. Add security ACL/rules.
4. Add inquiry relations and basic form integration.

### Phase 2 (Workflow)

1. Add Add Site Visit popup wizard.
2. Add Recommend Property popup wizard that creates recommended inquiry.
3. Add banners and inquiry-type UX.

### Phase 3 (API + Metrics)

1. Move site visit APIs to new model.
2. Move activity/funnel/portal performance site visit metrics to new model.

### Phase 4 (Migration and Cleanup)

1. Run scoped backfill migration.
2. Validate on prod clone.
3. Remove legacy fields after stabilization window.

## 12. Test Strategy

Add/modify tests for:

1. Config model integrity (`code` immutability, active/archive behavior).
2. Site visit create/transition/feedback validation.
3. Reschedule chain counts and lineage.
4. Recommend-property wizard creating recommended inquiry.
5. API endpoint output from new model.
6. Migration correctness for scoped statuses.

## 13. Risks and Mitigations

1. Risk: manager edits status labels/codes causing reporting drift.
   Mitigation: immutable machine `code`, editable `name`.

2. Risk: invalid feedback/status combinations.
   Mitigation: strict validation `feedback_option.status_id == visit.status_id`.

3. Risk: old and new fields diverge during transition.
   Mitigation: one-way sync from new model to legacy snapshots, short transition window.

4. Risk: RM confusion during workflow change.
   Mitigation: popup-first guided UX and clear inquiry-type banner.

## 14. Rollout and Verification Checklist

1. Verify seeded statuses/options appear in settings.
2. Verify manager can add/archive status/options from UI.
3. Verify RM can add site visit via popup on owned inquiry.
4. Verify reschedule increments chain counters.
5. Verify recommended inquiry creation via wizard.
6. Verify API responses from new model only.
7. Verify migration updates only scoped statuses.
8. Monitor for 3 to 7 days, then schedule legacy field removal.

## 15. Final Decision

Approved architecture:

1. Keep `leads.new` as inquiry model.
2. Implement configurable metadata-driven visit status/feedback.
3. Implement `lead.site.visit` as source of truth.
4. Replace inline recommended property interaction with wizard-created recommended inquiries.
5. Shift APIs and metrics fully to new model.
