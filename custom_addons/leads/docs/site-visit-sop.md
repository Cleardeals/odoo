# Site Visit SOP (RM + Manager)

- Module: leads
- Version: 1.0
- Last updated: 2026-03-30

This SOP defines how to schedule, reschedule, complete, and report site visits with full history tracking.

## 1. Core Rule

Every visit change must be recorded as a new site-visit event when rescheduling. Do not overwrite old visit records for reschedule tracking.

## 2. RM Workflow

1. Open inquiry in Leads.
2. Click Schedule a Visit.
3. Fill schedule date/time, status, optional feedback, and save.
4. For a time change, open the previous visit and set status to a reschedule-type status with a new schedule date/time.
5. The system creates a new visit record automatically and links it to the previous visit.
6. For completed visit outcomes, update the relevant visit status to a completed-type status.

## 3. Recommended Inquiry Workflow

1. Open a primary inquiry.
2. Click Recommend Property.
3. Select recommended property and RM.
4. Save.
5. The recommended inquiry source is inherited from the original inquiry source.

## 4. DPR and Performance Filters (RM)

Use Leads > Site Visits and apply the following filters:

1. My Visits: only your assigned site visits.
2. Scheduled: scheduled + rescheduled pipeline view.
3. Completed: conversion tracking.
4. Cancelled / No Show: leakage tracking.
5. Overdue: scheduled or rescheduled visits with date before today.
6. Rescheduled 2+: repeated reschedule chains needing intervention.
7. Scheduled Date: use built-in date ranges for day/week/month views.

Recommended grouping:

1. Group by RM for ownership checks.
2. Group by Status for stage split.
3. Group by Date for daily DPR snapshots.
4. Group by Inquiry for inquiry-level timeline checks.

## 5. Manager Reporting SOP

1. Open Leads > Site Visits.
2. Use Pivot view for DPR matrix by RM, status, and date.
3. Use Graph view for performance trend comparison.
4. Validate that rescheduled visits are increasing as new rows, not overwrites.
5. Use lead-level "Site Visits Today" search to review inquiry chains with event-based dates.

Suggested daily metrics:

1. Visits Scheduled = count of status type Scheduled + Rescheduled.
2. Visits Completed = count of status type Completed.
3. Reschedule Load = count of status type Rescheduled.
4. Drop-off = count of status type Cancelled + No Show.

## 6. Configuration SOP (Non-Technical Management)

For status setup:

1. Open Configuration > Site Visit Statuses.
2. Fill Name, Code, and Status Type.
3. Keep only one status type per row.
4. Avoid changing code after first save.

For feedback setup:

1. Open Configuration > Site Visit Feedback.
2. Select Status, add Name and Code, then save.
3. Use Requires Note only when mandatory comment is needed.
4. Use category/signal only for reporting refinement.

## 7. Operating Guardrails

1. Never delete historical visits to keep audit history intact.
2. Prefer reschedule events over direct edits for timeline integrity.
3. Always maintain original source continuity on recommended inquiry creation.
4. Archive unused status/feedback options instead of deleting.
