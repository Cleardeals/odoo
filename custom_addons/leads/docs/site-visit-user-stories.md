# Site Visit — RM User Stories

**Module:** `leads`  
**Last updated:** 2026-04-02  
**Scope:** All actions an RM can take against a `lead.site.visit` record, every edge
case and exception encountered in real field operations. Written as acceptance
criteria for implementation, QA and RM training.

---

## Contents

1. [Happy Path](#1-happy-path)
2. [Rescheduling](#2-rescheduling)
3. [No-Show Handling](#3-no-show-handling)
4. [Cancellation](#4-cancellation)
5. [Feedback & Notes](#5-feedback--notes)
6. [Overdue & Late Feedback](#6-overdue--late-feedback)
7. [Multi-Visit Chains](#7-multi-visit-chains)
8. [Inquiry State Interactions](#8-inquiry-state-interactions)
9. [Calendar & Visibility](#9-calendar--visibility)
10. [Manager / Admin Operations](#10-manager--admin-operations)
11. [System Guard Rails](#11-system-guard-rails)
12. [Known Gaps & Future Enhancements](#12-known-gaps--future-enhancements)

---

## 1. Happy Path

### US-01 — Schedule a first site visit
**As an RM**, when I have an inquiry where the buyer wants to view a property,  
I click **Add Site Visit** on the inquiry form, fill in:
- Scheduled date & time
- Status: **Scheduled** (pre-selected by default)
- Optional: feedback option (e.g. "Buyer confirmed slot") and notes

On save, a `lead.site.visit` record is created, the inquiry snapshot updates to
`current_status = site_visit_scheduled`, and the visit appears on my calendar.

**Acceptance criteria:**
- [ ] Status defaults to "Scheduled" — I must not need to touch the dropdown for the common case.
- [ ] Inquiry `site_visit_date` updates to the scheduled datetime.
- [ ] Visit appears on the calendar view under the correct date.
- [ ] I cannot save without a scheduled datetime.

---

### US-02 — Mark a visit as Completed
**As an RM**, after the buyer has visited the property, I open the visit (or use
"Update Latest Visit") and select status **Completed** with the appropriate feedback
(e.g. "Buyer interested", "Buyer not interested").

**Acceptance criteria:**
- [ ] Status transitions to Completed (terminal).
- [ ] Inquiry `current_status` updates to `site_visit_done`.
- [ ] Once Completed, the visit is locked — it cannot be rescheduled or cancelled.
- [ ] Feedback options shown are only those linked to the "Completed" status.

---

### US-03 — Create a second visit after completion
**As an RM**, after a visit is completed and the buyer wants another viewing,  
I click **Add Site Visit** again and create a fresh appointment.

**Acceptance criteria:**
- [ ] A new visit is created successfully (previous visit is terminal, no conflict).
- [ ] The new visit's `root_visit_id` is self-referencing (it starts a new visit chain).
- [ ] Both visits appear independently in the inquiry's visit history.

---

## 2. Rescheduling

### US-04 — Buyer requests reschedule before the visit
**As an RM**, the buyer calls and says they can't make the original slot. I click
**Update Latest Visit**, change the status to **Rescheduled**, set the new date & time,
and select feedback "Buyer Requested Time Change".

On Apply:
- The original visit is closed as terminal **Rescheduled** (stores the buyer's
  reason as feedback on that record).
- A fresh **Scheduled** visit is created with the new date, linked back to the
  original via `previous_visit_id`.

**Acceptance criteria:**
- [ ] Feedback for "Rescheduled" status (e.g. "Buyer Requested Time Change") is
      saved on the old (now terminal) visit.
- [ ] New visit has status **Scheduled**, not Rescheduled.
- [ ] New visit's `previous_visit_id` points to the original.
- [ ] `chain_reschedule_count` increments.
- [ ] Inquiry snapshot updates to new date and `site_visit_scheduled`.
- [ ] Calendar shows only the new active visit; the terminal old one does not appear
      by default.

---

### US-05 — RM-initiated reschedule (property unavailable)
**As an RM**, I learn the property is unavailable on the booked date. I reschedule
on behalf of the buyer, selecting "Property Unavailable" as feedback.

**Acceptance criteria:** Same gate checks as US-04.

---

### US-06 — Reschedule a visit that was already rescheduled (multi-hop)
**As an RM**, after rescheduling once, the buyer asks to change the time again.
I click Update Latest Visit on the new active visit and reschedule again.

**Acceptance criteria:**
- [ ] Each reschedule creates one new visit and closes the previous.
- [ ] `root_visit_id` remains the same as the very first visit in the chain.
- [ ] `reschedule_iteration` increments with each hop.
- [ ] All closed visits in the chain show status **Rescheduled** (terminal).
- [ ] Only the latest visit is active (not terminal).

---

### US-07 — Attempt to reschedule without supplying a new date
**As an RM**, I accidentally apply a Rescheduled status update without filling in
a new visit date & time.

**Acceptance criteria:**
- [ ] System blocks with: *"Set a new schedule date and time while rescheduling."*
- [ ] No new visit is created; original visit is unchanged.

---

### US-08 — Attempt to reschedule a terminal visit
**As an RM**, I try to open the quick-update wizard on a Completed or Cancelled visit
and apply a Rescheduled status.

**Acceptance criteria:**
- [ ] Calendar and form "Update Status" button must not be available for terminal
      visits (or clearly blocked with an actionable message).
- [ ] If bypassed at the wizard level, the model must still reject the transition.

---

## 3. No-Show Handling

### US-09 — Buyer did not show up
**As an RM**, the buyer did not appear at the scheduled time. I mark the visit as
**Did Not Show Up** and add notes.

**Acceptance criteria:**
- [ ] Visit transitions to "Did Not Show Up" (not terminal by default).
- [ ] Inquiry snapshot is **not** updated to `site_visit_done` (the visit did not
      happen).
- [ ] The overdue-visit alert clears since the status has been updated.

---

### US-10 — Reschedule after a no-show
**As an RM**, after a no-show, the buyer responds and wants to book a new slot.
I use **Update Latest Visit** → **Rescheduled** to create a new visit.

**Acceptance criteria:**
- [ ] Same reschedule contract as US-04 — old DNP visit closed, new Scheduled visit
      created.
- [ ] Reschedule chain correctly links through the DNP visit.

---

### US-11 — Multiple no-shows in a chain
**As an RM**, the buyer is a repeat no-show. Each no-show is followed by a
reschedule.

**Acceptance criteria:**
- [ ] `chain_reschedule_count` reflects total reschedules since root.
- [ ] All past no-show visits are traceable via `previous_visit_id`.

---

## 4. Cancellation

### US-12 — RM cancels a visit (buyer withdrew)
**As an RM**, the buyer is no longer interested or has withdrawn. I click
**Cancel Visit** on the visit form, which pre-selects the **Cancelling** status.
I add a reason as feedback.

**Acceptance criteria:**
- [ ] Visit transitions to Cancelling (terminal).
- [ ] Inquiry status is NOT updated to `site_visit_done` — cancellation is a loss
      signal, not a completion.
- [ ] Cancel button disappears for visits already in a terminal state.

---

### US-13 — Attempt to create a new active visit when one is already open
**As an RM**, I accidentally click **Add Site Visit** while there is already a
Scheduled or Did-Not-Show-Up visit for the same inquiry.

**Acceptance criteria:**
- [ ] System blocks with: *"This inquiry already has an active visit
      ({visit name}). Update or close it before creating a new one."*
- [ ] No duplicate visit is created.

---

## 5. Feedback & Notes

### US-14 — Add feedback when scheduling
**As an RM**, when I first schedule a visit, I can optionally add feedback
(e.g. "Buyer Confirmed Slot") and free-text notes.

**Acceptance criteria:**
- [ ] Feedback dropdown shows only options linked to the selected status.
- [ ] Changing the status in the wizard clears/filters the feedback dropdown.
- [ ] Notes are optional unless the selected feedback option has `requires_note=True`.

---

### US-15 — Feedback requires a note
**As an RM**, I pick a feedback option that is flagged as "requires note"
(e.g. "Other Reason") without filling in the notes field.

**Acceptance criteria:**
- [ ] System blocks with: *"Feedback note is required for the selected feedback
      option."*

---

### US-16 — Feedback mismatch (wrong status selected)
**As an RM**, I pick a feedback option that belongs to a different status than the
one I have selected in the wizard.

**Acceptance criteria:**
- [ ] Dropdown domain filter (`[('status_id','=',status_id)]`) prevents mismatches
      in the UI.
- [ ] The model-level constraint fires as a last defense if the domain is bypassed
      (e.g. API write).
- [ ] Terminal status visits holding reschedule-reason feedback are exempt from
      this check.

---

## 6. Overdue & Late Feedback

### US-17 — Scheduled date has passed without an update
**As an RM**, a visit I scheduled for April 12 is now past its date and I haven't
logged the outcome.

**Acceptance criteria:**
- [ ] The visit form displays a warning: *"Overdue Visit — This visit's scheduled
      date has passed without a status update."*
- [ ] `is_overdue_open = True` as long as status remains Scheduled or Rescheduled
      and the date is in the past.
- [ ] Warning disappears as soon as I update the status to any outcome.

---

### US-18 — Late feedback with correct visit date (buyer visited on a different day)
**As an RM**, I scheduled a visit for April 12. On April 16, the buyer says
*"I actually went on April 14."*

**Current system behaviour:**
The `scheduled_datetime` on the visit stays as April 12. The RM should update it
to April 14 BEFORE marking the visit Completed, so the actual visit date is
recorded correctly for reporting.

**Acceptance criteria:**
- [ ] The quick-update wizard allows editing `scheduled_datetime` even when marking
      a visit as Completed (not just on Rescheduled status).
- [ ] After update: `scheduled_datetime = April 14`, `status = Completed`.
- [ ] Inquiry snapshot `site_visit_date` reflects April 14.

> **Gap:** As of v1.4.0, the quick-update wizard only shows the datetime field
> when `is_reschedule_status = True`. A separate `actual_visit_datetime` field or
> an unlock of the field for Completed transitions is needed. See
> [Known Gaps §12](#12-known-gaps--future-enhancements).

---

### US-19 — Backdated visit entry
**As an RM**, I forgot to log a visit that happened two weeks ago. I create a
visit record with `scheduled_datetime` set to the past date.

**Acceptance criteria:**
- [ ] System allows past datetimes — there is no future-only guard on creation.
- [ ] `is_overdue_open` flags the record immediately since the date is in the past
      and the status is Scheduled.
- [ ] RM should immediately update the status to the actual outcome (Completed,
      No-Show, etc.).

---

### US-20 — Feedback logged by a different RM (handover)
**As a manager**, I reassign an inquiry from RM A to RM B mid-cycle. RM B needs
to log the outcome of a visit originally booked by RM A.

**Acceptance criteria:**
- [ ] Any RM with write access can update any visit (not owner-locked).
- [ ] The `assigned_rm_id` on the visit can be updated if needed.
- [ ] Audit trail (chatter) shows who made the update and when.

---

## 7. Multi-Visit Chains

### US-21 — View full visit history for an inquiry
**As an RM**, I want to see every visit ever scheduled for an inquiry, including
all rescheduled, cancelled, and completed ones.

**Acceptance criteria:**
- [ ] The "Lead Visits" stat button on the inquiry form shows the total count
      (including terminal visits).
- [ ] Clicking it opens a filtered list view with all visits (active and terminal).
- [ ] Each visit shows: date, status, RM, feedback, notes.

---

### US-22 — Visit for a recommended (secondary) inquiry
**As an RM**, a buyer from a primary inquiry has been recommended a different
property. A new inquiry is created for the recommended property. I schedule a
visit for the recommended inquiry.

**Acceptance criteria:**
- [ ] Visit creation works identically for recommended inquiries as for primary ones.
- [ ] Visit history of the recommended inquiry is separate from the primary.

---

### US-23 — Extreme reschedule chain (5+ reschedules)
**As a manager**, some buyers reschedule many times.

**Acceptance criteria:**
- [ ] No hard limit enforced by the system on `reschedule_iteration`.
- [ ] `chain_reschedule_count` correctly reflects the depth from root.
- [ ] When viewing the inquiry, the RM sees the current (latest) active visit, not
      all historical entries.
- [ ] *(Future)* Management may want an alert when `reschedule_iteration >= 3`.

---

## 8. Inquiry State Interactions

### US-24 — Inquiry archived while a visit is active
**As a manager**, I archive an inquiry that still has a scheduled visit.

**Acceptance criteria:**
- [ ] Visit records are cascade-deleted or archived along with the inquiry  
      (currently `ondelete="cascade"` on `inquiry_id`).
- [ ] If cascade-archived, the calendar should no longer show those visits.
- [ ] System should warn the manager if archiving an inquiry with active visits.

---

### US-25 — Property changed on inquiry after visit is scheduled
**As an RM**, I update the property on the inquiry form after a visit has been
created for the original property.

**Acceptance criteria:**
- [ ] The visit's `property_base_id` is **not** auto-changed (it was booked for that
      specific property).
- [ ] If the RM wants to change the property for the visit, they must update the
      visit record directly.

---

### US-26 — RM assigned to inquiry changes
**As a manager**, I reassign an inquiry to a different RM while a visit is
scheduled.

**Acceptance criteria:**
- [ ] Future visit creation defaults `assigned_rm_id` from the inquiry's new RM.
- [ ] Existing visit records retain the original RM unless explicitly updated.

---

## 9. Calendar & Visibility

### US-27 — Calendar default view and color coding
**As an RM**, I open the Site Visits calendar.

**Acceptance criteria:**
- [ ] Default view is **Month** (prevents Sunday/busy-day overflow).
- [ ] Each visit is color-coded by its status; colors are manager-configurable
      in the Status setup form.
- [ ] Overflowing days (e.g. Sundays with 100+ events) collapse to "+N more" — I
      can click to drill into day view.
- [ ] Day and week views are also available via the scale selector.

---

### US-28 — "Reschedule Visit" button on calendar popover
**As an RM**, I click a visit event in the calendar and see the Reschedule button
in the popover.

**Acceptance criteria:**
- [ ] Reschedule button is visible only for active (Scheduled / Did Not Show Up)
      visits — hidden for terminal states.
- [ ] Clicking opens the quick-update wizard pre-loaded with Rescheduled status.

---

## 10. Manager / Admin Operations

### US-29 — Create or modify status configuration
**As a manager**, I go to Configuration → Visit Statuses to add a new status
(e.g. "Site Visit Pending Confirmation").

**Acceptance criteria:**
- [ ] Name, Code (immutable after creation), Status Type, Sequence, Color, and
      Is Terminal are all editable.
- [ ] Code uniqueness is enforced.
- [ ] New status appears in the wizard dropdowns immediately (active=True).

---

### US-30 — Create or modify feedback options
**As a manager**, I add a new feedback option "Buyer Wants Comparison Property"
under the Scheduled status.

**Acceptance criteria:**
- [ ] Feedback option is linked to the correct status.
- [ ] It appears in the feedback dropdown only when that status is selected.
- [ ] I can mark it as `requires_note=True` to force RMs to explain.

---

### US-31 — Archive a status without breaking existing visits
**As a manager**, I archive a status that is no longer in use.

**Acceptance criteria:**
- [ ] Archived status disappears from wizard dropdowns (`active=True` domain).
- [ ] Existing visit records that already have the archived status still display
      it correctly (display_name shown even for inactive M2o values).
- [ ] `is_overdue_open` and other computed fields continue to read the status
      flags correctly.

---

## 11. System Guard Rails

### GR-01 — One active visit per inquiry
A new visit can only be created via **Add Site Visit** if no non-terminal visit
exists for the same inquiry. Bypassed only by the internal reschedule flow
(`skip_active_visit_check` context flag).

### GR-02 — Reschedule requires a new datetime
`write()` to a Rescheduled status without `scheduled_datetime` in the payload is
rejected.

### GR-03 — Feedback must match status (non-terminal)
`feedback_option_id.status_id` must equal the visit's `status_id`, except for
terminal visits which hold the reschedule-reason feedback from the trigger event.

### GR-04 — Reschedule lineage
A visit with `is_reschedule_status=True` must have a `previous_visit_id`.

### GR-05 — Previous visit belongs to same inquiry
`previous_visit_id.inquiry_id` must equal `visit.inquiry_id`.

### GR-06 — Property required
A visit requires a property (`property_base_id`). If not supplied, it falls back
to the inquiry's property. If the inquiry also has no property, creation is blocked.

---

## 12. Known Gaps & Future Enhancements

| ID | Gap | Impact | Suggested Fix |
|----|-----|--------|---------------|
| GAP-01 | No `actual_visit_datetime` field — when a buyer visits on a different day than scheduled, the RM has no way to record the real date separately from the slot date. | Reporting inaccuracies on visit conversion time. | Add `actual_visit_datetime` or allow editing `scheduled_datetime` in the quick-update wizard for Completed transitions. |
| GAP-02 | "Did Not Show Up" is not a terminal status — prevents direct re-booking via "Add Site Visit". RMs must always use the reschedule path. | Slight friction; also conceptually odd if "Did Not Show Up" is considered a closed event. | Decision: mark `did_not_show_up` as `is_terminal=True` and create a dedicated "Re-book After No Show" reschedule path, or leave as-is. |
| GAP-03 | No hard limit on reschedule iterations. A buyer who reschedules 10 times shows no management alert. | Missed escalation opportunity. | Add a management alert (digest or automated action) when `reschedule_iteration >= 3`. |
| GAP-04 | No warning when archiving an inquiry with active visits. The cascade-delete silently removes future appointments. | Risk of data loss. | Add a pre-unlink check that warns when active visits exist. |
| GAP-05 | Inquiry snapshot (`site_visit_date`) always reflects the last-synced visit, but does not indicate WHICH visit (first, latest, etc.). | Confusing when a buyer has been rescheduled 4 times. | Store `latest_site_visit_id` (already exists) and expose its date in the inquiry list view. |
| GAP-06 | Calendar "Reschedule" button on popover uses `status_is_scheduled` and `status_is_rescheduled` booleans loaded at open time — stale after a background update without refresh. | Rare: popover shows reschedule button on a visit that was just completed in another tab. | Reload `rawRecord` on popover open or listen to bus event. |
