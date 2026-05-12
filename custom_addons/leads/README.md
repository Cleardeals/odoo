# Leads Module — Complete Model Reference

> Centralized lead ingestion, source normalization, assignment automation, RM execution workflows, and site visit lifecycle management for Cleardeals.

**Module name:** `leads`  
**Version:** `1.5.0`  
**Odoo version:** `19.0`  
**License:** `LGPL-3`  
**Last updated:** `2026-05-08`  
**Owner:** Cleardeals Tech

---

## Quick navigation

- [Module overview](#module-overview)
- [Model index](#model-index)
- [Model: `leads.new`](#model-leadsnew) — canonical lead record
- [Model: `lead.score`](#model-leadscore) — BigQuery-scored lead
- [Model: `lead.source.category`](#model-leadsourcecategory) — source classification
- [Model: `lead.source`](#model-leadsource) — source registry
- [Model: `lead.property.interest`](#model-leadpropertyinterest) — recommended property link
- [Model: `lead.site.visit.status`](#model-leadsitevisit status) — visit status taxonomy
- [Model: `lead.site.visit.feedback.option`](#model-leadsitevisitfeedbackoption) — feedback options
- [Model: `lead.site.visit`](#model-leadsitevisit) — site visit record
- [Model: `lead.olx.account`](#model-leadolxaccount) — OLX dealer credentials
- [Model: `leads.bde`](#model-leadsbde) — BDE registry
- [Model: `whatsapp.response`](#model-whatsappresponse) — WhatsApp response tracking
- [Cross-model relationships](#cross-model-relationships)
- [Site visit lifecycle](#site-visit-lifecycle)

---

## What this module does

The leads module ingests buyer inquiries from webhooks, cron pulls, and manual channels, standardizes source metadata, resolves property links, and routes leads to RMs. It keeps two operational layers in sync:

- `leads.new`: ingestion, assignment, and inquiry-level timeline
- `lead.score`: scored and follow-up layer

The module also owns the complete **site visit lifecycle**: creating, rescheduling, cancelling, and tracking visit appointments per inquiry, with a visual timeline rendered directly on the lead and inquiry forms.

---

## Model index

| Model | DB table | Purpose |
|---|---|---|
| `leads.new` | `leads_new` | Canonical lead ingestion, assignment, and inquiry record |
| `lead.score` | `lead_score` | BigQuery-scored lead lifecycle and follow-up workflow |
| `lead.source.category` | `lead_source_category` | Source classification (`portal` vs `manual`) |
| `lead.source` | `lead_source` | Source registry with portal code and fallback RM routing |
| `lead.property.interest` | `lead_property_interest` | Recommended property links and per-property visit tracking |
| `lead.site.visit.status` | `lead_site_visit_status` | Configurable status taxonomy with semantic flags |
| `lead.site.visit.feedback.option` | `lead_site_visit_feedback_option` | Feedback options scoped to a specific status |
| `lead.site.visit` | `lead_site_visit` | Individual site visit appointment record |
| `lead.olx.account` | `lead_olx_account` | OLX dealer account credentials and polling state |
| `leads.bde` | `leads_bde` | Business Development Executive registry |
| `whatsapp.response` | `whatsapp_response` | WhatsApp response tracking and RM processing |

---

## Model: `leads.new`

**DB table:** `leads_new`  
**Description:** Canonical lead record. Every buyer inquiry — whether from a portal webhook, OLX cron, Housing.com API, or manual entry — lands here. This is the primary object for RM workflows.

**Inherits:** `mail.thread`, `mail.activity.mixin` (chatter + activity tracking)  
**Order:** `create_date desc`

### Identity fields

| Field | Type | Required | Stored | Description |
|---|---|---|---|---|
| `name` | `Char` | ✓ | ✓ | Lead / buyer name. Auto-set from portal payload on ingestion. |
| `phone` | `Char` | — | ✓ | Raw phone number as received. Indexed. Tracking enabled. |
| `email` | `Char` | — | ✓ | Email address. Indexed. Tracking enabled. |

### Source fields

| Field | Type | Required | Stored | Description |
|---|---|---|---|---|
| `source_id` | `Many2one → lead.source` | — | ✓ | Which source this lead came from (e.g. Housing.com, OLX, Manual). Indexed. Tracking enabled. |
| `source_type` | `Selection` | — | ✓ (related) | Related from `source_id.source_type`. Values: `portal`, `manual`. |
| `is_portal_source` | `Boolean` | — | ✗ (computed) | True if `source_id.category_id.source_type == 'portal'`. Not stored — recomputed live. |
| `portal_name` | `Char` | — | ✓ (related) | Related from `source_id.name`. Stored for historical rows. |
| `project_name` | `Char` | — | ✓ | Project name as received from the portal payload. |
| `portal_property_id` | `Char` | — | ✓ | The listing ID on the portal (e.g. OLX `adId`, 99acres listing number). Used for property matching. Indexed. |
| `raw_data` | `Text` | — | ✓ | Full raw JSON payload from the portal webhook — kept for debugging. |

### Assignment and processing fields

| Field | Type | Required | Stored | Description |
|---|---|---|---|---|
| `state` | `Selection` | ✓ | ✓ | Processing state. Values: `new`, `assigned`, `failed`. Default: `new`. Indexed. Tracking enabled. |
| `user_id` | `Many2one → res.users` | — | ✓ | Assigned Relationship Manager. Tracking enabled. |
| `property_base_id` | `Many2one → property.base` | — | ✓ | Primary property linked to this lead. Set by the assignment logic. Indexed. Tracking enabled. |
| `property_id` | `Many2one → property.inventory` | — | ✓ | **Legacy field.** Points to the old `property.inventory` model. Kept for historical data integrity — do not use for new integrations. |
| `process_notes` | `Text` | — | ✓ | Auto-appended audit trail of assignment events, re-links, and failures. |
| `is_webhook_sent` | `Boolean` | — | ✓ | True once this lead has been dispatched to the n8n outbound webhook. Default: `False`. Indexed. |

### Status and workflow fields

| Field | Type | Required | Stored | Description |
|---|---|---|---|---|
| `current_status` | `Selection` | ✓ | ✓ | RM's active call/engagement status. Default: `lead`. Tracking enabled. See status values below. |
| `remarks` | `Text` | — | ✓ | Free-text call remarks from the RM. Tracking enabled. |
| `feedback_general` | `Selection` | — | ✓ | Used when status indicates no site visit. Values: `buyer_did_not_visit_property`, `buyer_not_interested`, `buyer_not_picking_call`, `visit_needs_to_be_rescheduled`, `other`. |
| `feedback_site_visit_done` | `Selection` | — | ✓ | Used after a site visit completes. Values: `buyer_liked_property`, `buyer_requirement_closed`, `buyer_visit_from_outside`, `buyer_not_pickup_call`, `planning_for_second_visit`, `negotiation_stage`, `visit_done_confirmed_by_owner`, `looking_for_more_options`, `price_is_high`, `location_mismatch`, `deal_closed`, `other`. |
| `is_ops_sale_lead` | `Boolean` | — | ✓ | Marks this as an Ops Sale Lead (requires a BDE). Default: `False`. Tracking enabled. |
| `bde_id` | `Many2one → leads.bde` | — | ✓ | Business Development Executive assigned to this ops sale lead. Required when `is_ops_sale_lead=True`. Indexed. Tracking enabled. |

### `current_status` selection values

| Value | Label |
|---|---|
| `busy` | Busy |
| `lead` | Lead |
| `ringing` | Ringing |
| `call_back_later` | Call Back Later |
| `site_visit_scheduled` | Site Visit Scheduled |
| `option_not_matching_requirements` | Option Not Matching Requirements |
| `details_shared_of_property` | Details Shared of Property |
| `no_requirements` | No Requirements |
| `detail_shared_and_interested_for_site_visit` | Detail Shared and Interested for Site Visit |
| `switched_off` | Switched Off |
| `requirement_closed` | Requirement Closed |
| `property_sold_out` | Property Sold Out |
| `rescheduled` | Rescheduled |
| `budget_not_sufficient` | Budget Not Sufficient |
| `site_visit_done` | Site Visit Done |
| `number_not_in_use_wrong_number` | Number Not in Use / Wrong Number |
| `other` | Other |

### Site visit (legacy) fields on `leads.new`

> These fields belong to the legacy site-visit tracking on the lead itself. The full visit lifecycle now lives in `lead.site.visit`. These remain for backward compatibility.

| Field | Type | Stored | Description |
|---|---|---|---|
| `site_visit_date` | `Datetime` | ✓ | Legacy datetime for the main property site visit. Indexed. Tracking enabled. |
| `site_visit_date_only` | `Date` | ✓ (computed) | Date-only extract of `site_visit_date` for fast filter queries. |
| `first_contact_datetime` | `Datetime` | ✓ | Timestamp when the RM first contacted this lead. Set once, never updated. Tracking enabled. |

### Computed property fields (denormalized from `property.base`)

These are stored related fields populated automatically when `property_base_id` is set:

| Field | Type | Stored | Source |
|---|---|---|---|
| `base_property_tag` | `Char` | ✓ | `property_base_id.property_tag` |
| `base_property_bhk` | `Char` | ✓ | `property_base_id.bhk` |
| `base_property_location` | `Char` | ✓ | `property_base_id.location` |
| `base_property_city` | `Char` | ✓ | `property_base_id.city` |
| `base_property_owner_name` | `Char` | ✓ | `property_base_id.owner_name` |
| `base_property_link` | `Char` | ✓ | `property_base_id.property_link` |

### BDE computed access field

| Field | Type | Stored | Description |
|---|---|---|---|
| `bde_allowed_ids` | `Many2many → leads.bde` | ✗ (computed) | Context-sensitive: managers see all BDEs; RMs see only BDEs where their user is in `allowed_rm_ids` (or BDE has no restriction). Not stored. |

### Relationship fields

| Field | Type | Stored | Description |
|---|---|---|---|
| `interest_ids` | `One2many → lead.property.interest` | ✓ | All recommended properties for this lead. |
| `all_associated_properties` | `Many2many → property.base` | ✓ (computed) | Union of `property_base_id` + all `interest_ids.property_base_id`. |

### Inquiry extension fields

| Field | Type | Stored | Description |
|---|---|---|---|
| `inquiry_type` | `Selection` | ✓ | `primary` (default) or `recommended`. Required. Indexed. Tracking enabled. |
| `parent_inquiry_id` | `Many2one → leads.new` | ✓ | Parent inquiry when `inquiry_type='recommended'`. Indexed. Tracking enabled. |
| `child_inquiry_ids` | `One2many → leads.new` | ✗ | All recommended child inquiries of this lead. |
| `site_visit_ids` | `One2many → lead.site.visit` | ✗ | All site visits linked to this inquiry. |
| `latest_site_visit_id` | `Many2one → lead.site.visit` | ✗ (computed) | Most recent site visit by `scheduled_datetime`. Not stored. |
| `site_visit_count` | `Integer` | ✗ (computed) | Count of all `site_visit_ids`. Not stored. |
| `all_phone_site_visit_ids` | `Many2many → lead.site.visit` | ✗ (computed) | All visits across every inquiry sharing the same `phone`. Used for the overall timeline. Not stored. Uses `sudo()` to bypass RM record rules. |
| `inquiry_timeline_html` | `Html` | ✗ (computed) | Rendered HTML timeline for this inquiry's visits only. `sanitize=False`. |
| `overall_timeline_html` | `Html` | ✗ (computed) | Rendered HTML timeline across all visits for the same phone number. `sanitize=False`. |

### Utility / display fields

| Field | Type | Stored | Description |
|---|---|---|---|
| `phone_whatsapp_url` | `Char` | ✗ (computed) | `whatsapp://send?phone=91XXXXXXXXXX` deep link. |
| `phone_whatsapp_html` | `Html` | ✗ (computed) | Clickable WhatsApp icon + phone number HTML. `sanitize=False`. |
| `create_date_only` | `Date` | ✓ (computed) | IST-corrected creation date extracted from `create_date`. Handles midnight UTC crossover. |
| `x_migrated_date` | `Datetime` | ✓ | Migration utility field. |

### Constraints

| Name | Rule |
|---|---|
| `_check_bde_required_for_ops_sale` | If `is_ops_sale_lead=True`, `bde_id` must be set. |
| `_check_bde_allowed_for_rm` | If `bde_id.allowed_rm_ids` is non-empty, `user_id` must be in that list. |

---

## Model: `lead.score`

**DB table:** `lead_score`  
**Description:** BigQuery-scored lead record. Populated by the BigQuery sync wizard. Contains the predicted ML score, contact details, property context, follow-up management, and WhatsApp response history. This layer is parallel to — not derived from — `leads.new`.

**BigQuery source:** Dataset `lead_scoring`, table `whatsapp_automation_list`, project `cleardeals-459513`  
**Order:** `predicted_score desc`

### Core fields

| Field | Type | Required | Stored | Description |
|---|---|---|---|---|
| `name` | `Char` | ✓ | ✓ | Lead / buyer name. |
| `assigned_rm_id` | `Many2one → res.users` | — | ✓ | Assigned RM as synced from BigQuery. |
| `standardized_phone` | `Char` | — | ✓ | Cleaned phone number (used as the WhatsApp dispatch key). |
| `predicted_score` | `Float` | — | ✓ | ML-predicted lead score from BigQuery. Higher = more likely to convert. |
| `x_migrated_write_date` | `Datetime` | — | ✓ | Timestamp of the most recent BigQuery sync update for this record. |

### Status and workflow

| Field | Type | Required | Stored | Description |
|---|---|---|---|---|
| `current_status` | `Selection` | ✓ | ✓ | Current call / engagement status. Default: `lead`. Same value set as `leads.new.current_status`. |
| `state` | `Selection` | ✓ | ✓ | Secondary status field (same values as `current_status`). Default: `lead`. Required. |
| `next_follow_up_date` | `Date` | — | ✓ (computed, editable) | Auto-set: day after site visit date for scheduled/rescheduled status; today if never set. Manually overridable. |
| `is_actionable_today` | `Boolean` | — | ✓ (computed) | `True` when `next_follow_up_date` is today or earlier (or unset). Updated by a scheduled action. |
| `notes` | `Text` | — | ✓ | Free-text notes for the RM. |
| `site_visit_scheduled_date` | `Date` | — | ✓ | Date the site visit is scheduled for. Drives `next_follow_up_date` auto-logic. |
| `feedback_general` | `Selection` | — | ✓ | General feedback (used when no site visit yet). Values: `buyer_did_not_visit_property`, `buyer_not_interested`, `buyer_not_picking_call`, `visit_needs_to_be_rescheduled`, `other`. |
| `feedback_site_visit_done` | `Selection` | — | ✓ | Feedback after site visit. Values: `requirements_not_matching`, `buyer_liked_property`, `buyer_requirement_closed`, `buyer_visit_from_outside`, `buyer_not_pickup_call`, `other`. |

### Property context (denormalized from BigQuery)

All fields below are `Char` type, stored `True`, populated on BigQuery sync:

| Field | BigQuery column | Description |
|---|---|---|
| `project_name` | — | Property project name. |
| `property_type` | — | Property type string. |
| `property_tag` | — | Property short tag. |
| `property_address` | — | Property address. |
| `bhk` | — | BHK configuration (e.g. "2 BHK"). |
| `price_range` | — | Price range in Lacs. |
| `carpet_area` | — | Carpet area in Sqft. |
| `super_built_up_area` | — | Super built-up area. |
| `property_link` | — | URL to the property listing. |
| `location` | — | Location / locality. |
| `property_on_floor` | — | Floor number. |
| `property_facing` | — | Direction the property faces. |
| `furniture_details` | — | Furniture status. |
| `age_of_property` | — | Age of the property. |
| `parking_details` | — | Parking info. |
| `bathroom` | — | Number of bathrooms. |
| `offer_price` | — | Offer price in Lacs. |

### WhatsApp response relationship

| Field | Type | Stored | Description |
|---|---|---|---|
| `whatsapp_response_ids` | `One2many → whatsapp.response` | ✓ | All WhatsApp replies received for this lead. |
| `whatsapp_response_count` | `Integer` | ✗ (computed) | Count of `whatsapp_response_ids`. Not stored. |

---

## Model: `lead.source.category`

**DB table:** `lead_source_category`  
**Description:** Groups lead sources into broad classifications. The `source_type` drives whether property matching and fallback RM logic applies.

**Order:** `sequence, id`

| Field | Type | Required | Stored | Description |
|---|---|---|---|---|
| `name` | `Char` | ✓ | ✓ | Category name (e.g. "Real Estate Portals", "Manual"). Indexed. |
| `code` | `Char` | ✓ | ✓ | Unique code identifier (immutable once set). Indexed. |
| `sequence` | `Integer` | — | ✓ | Display ordering. Default: `10`. |
| `active` | `Boolean` | — | ✓ | Soft-delete flag. Default: `True`. Indexed. |
| `source_type` | `Selection` | ✓ | ✓ | `portal` → portal-originated leads (triggers property matching); `manual` → human-entered leads. Default: `manual`. Indexed. |

**Constraint:** `_code_uniq` — `code` must be globally unique.

---

## Model: `lead.source`

**DB table:** `lead_source`  
**Description:** Individual lead source record (e.g. "Housing.com", "OLX", "Walk-In"). Each portal source maps to a canonical portal code used for property matching. A fallback RM handles unmatched portal leads.

**Order:** `sequence, name, id`

| Field | Type | Required | Stored | Description |
|---|---|---|---|---|
| `name` | `Char` | ✓ | ✓ | Source name (e.g. "Housing.com", "OLX"). Globally unique. Indexed. |
| `sequence` | `Integer` | — | ✓ | Display ordering. Default: `10`. |
| `active` | `Boolean` | — | ✓ | Soft-delete flag. Default: `True`. Indexed. |
| `category_id` | `Many2one → lead.source.category` | ✓ | ✓ | Parent category. `ondelete=restrict`. Indexed. |
| `source_type` | `Selection` | — | ✓ (related) | Related from `category_id.source_type`. Stored for query efficiency. |
| `portal_code` | `Selection` | — | ✓ | Canonical portal identifier. Values: `99acres`, `Housing.com`, `MagicBricks`, `OLX`. Required when `source_type='portal'`. Indexed. |
| `default_rm_user_id` | `Many2one → res.users` | — | ✓ | Fallback RM: used when a portal lead cannot be matched to a specific property. |

**Constraints:** `_name_uniq` — `name` must be globally unique. `_check_portal_code_consistency` — portal sources must have a `portal_code`; manual sources must not.

---

## Model: `lead.property.interest`

**DB table:** `lead_property_interest`  
**Description:** A single recommended property interest record linking a lead to a property (other than the primary `property_base_id`). Tracks per-property status, site visit date, and feedback. All changes are automatically audited to the parent lead's chatter.

**Order:** `create_date desc`

| Field | Type | Required | Stored | Description |
|---|---|---|---|---|
| `lead_id` | `Many2one → leads.new` | ✓ | ✓ | Parent lead. `ondelete=cascade`. |
| `property_base_id` | `Many2one → property.base` | — | ✓ | Recommended property. Unique per `(lead_id, property_base_id)`. Indexed. |
| `current_status` | `Selection` | ✓ | ✓ | Per-property engagement status. Default: `lead`. Same value set as `leads.new.current_status`. |
| `remarks` | `Text` | — | ✓ | RM notes specific to this property recommendation. |
| `site_visit_date` | `Datetime` | — | ✓ | Site visit date/time for this recommended property. |
| `site_visit_date_only` | `Date` | — | ✓ (computed) | Date-only part of `site_visit_date` — stored for fast filter queries. |
| `feedback_general` | `Selection` | — | ✓ | Feedback when no visit occurred. Values: `buyer_did_not_visit_property`, `buyer_not_interested`, `buyer_not_picking_call`, `visit_needs_to_be_rescheduled`, `other`. |
| `feedback_site_visit_done` | `Selection` | — | ✓ | Feedback after site visit. Values: `buyer_liked_property`, `buyer_requirement_closed`, `buyer_visit_from_outside`, `buyer_not_pickup_call`, `planning_for_second_visit`, `negotiation_stage`, `visit_done_confirmed_by_owner`, `looking_for_more_options`, `price_is_high`, `location_mismatch`, `deal_closed`, `other`. |

**Denormalized fields from `property.base`** (all stored):

| Field | Source |
|---|---|
| `base_property_bhk` | `property_base_id.bhk` |
| `base_property_location` | `property_base_id.location` |
| `base_property_city` | `property_base_id.city` |
| `base_property_link` | `property_base_id.property_link` |
| `base_property_owner_name` | `property_base_id.owner_name` |

**Constraint:** `_lead_prop_uniq` — a property can only be recommended once per lead.

**Chatter auditing:** `create`, `write`, and `unlink` are overridden to post formatted notes on `lead_id` whenever a recommended property is added, changed, or removed.

---

## Model: `lead.site.visit.status`

**DB table:** `lead_site_visit_status`  
**Description:** Configurable status taxonomy for site visits. Each record carries boolean semantic flags that drive the reschedule flow, UI colour coding, and terminal-state guards.

**Order:** `sequence, id`

| Field | Type | Required | Stored | Description |
|---|---|---|---|---|
| `name` | `Char` | ✓ | ✓ | Display name (e.g. "Scheduled", "Completed"). Indexed. |
| `code` | `Char` | ✓ | ✓ | Immutable identifier (e.g. `scheduled`, `completed`, `superseded`). Indexed. Unique. |
| `sequence` | `Integer` | — | ✓ | Display ordering. Default: `10`. |
| `active` | `Boolean` | — | ✓ | Soft-delete flag. Default: `True`. Indexed. |
| `is_terminal` | `Boolean` | — | ✓ | When `True`, the visit record is locked from further edits. Default: `False`. |
| `is_scheduled_status` | `Boolean` | — | ✓ | Visit is upcoming and active. Default: `False`. |
| `is_reschedule_status` | `Boolean` | — | ✓ | Setting this status triggers the reschedule write flow. Default: `False`. |
| `is_completed_status` | `Boolean` | — | ✓ | Visit happened — hard terminal. Default: `False`. |
| `is_cancelled_status` | `Boolean` | — | ✓ | Visit did not happen — hard terminal (except `code='superseded'`). Default: `False`. |
| `is_no_show_status` | `Boolean` | — | ✓ | Buyer did not appear — hard terminal. Default: `False`. |
| `status_type` | `Selection` | — | ✗ (computed) | Derived convenience label: `scheduled`, `rescheduled`, `completed`, `cancelled`, `no_show`, `custom`. Not stored. |
| `allow_feedback_note` | `Boolean` | — | ✓ | Whether the feedback note text field is shown for this status. Default: `True`. |
| `color` | `Integer` | — | ✓ | Odoo kanban colour index. Default: `0`. |

**Constraints:** `_code_uniq` — code must be globally unique. `_check_single_status_type_flag` — at most one type boolean may be `True`. `code` is immutable once saved.

---

## Model: `lead.site.visit.feedback.option`

**DB table:** `lead_site_visit_feedback_option`  
**Description:** Selectable feedback options available after a site visit, scoped to a specific status. Each option carries a category and management signal for dashboard aggregation.

**Order:** `status_id, sequence, id`

| Field | Type | Required | Stored | Description |
|---|---|---|---|---|
| `name` | `Char` | ✓ | ✓ | Display name of the feedback option. Indexed. |
| `code` | `Char` | ✓ | ✓ | Globally unique immutable code. Auto-generated from `name` if not provided (slugified). Indexed. |
| `status_id` | `Many2one → lead.site.visit.status` | ✓ | ✓ | The status this option belongs to. `ondelete=restrict`. Indexed. |
| `category` | `Selection` | ✓ | ✓ | Semantic category: `intent`, `blocker`, `property`, `pricing`, `operations`, `other`. Default: `other`. Indexed. |
| `management_signal` | `Selection` | ✓ | ✓ | Dashboard signal: `positive_intent`, `risk`, `loss_reason`, `neutral`. Default: `neutral`. Indexed. |
| `requires_note` | `Boolean` | — | ✓ | Whether selecting this option requires a free-text note. Default: `False`. |
| `sequence` | `Integer` | — | ✓ | Display ordering within its status. Default: `10`. |
| `active` | `Boolean` | — | ✓ | Soft-delete flag. Default: `True`. Indexed. |

**Constraints:** `_code_uniq` — code must be globally unique. `_status_code_uniq` — code must be unique within a status. `code` is immutable once saved.

---

## Model: `lead.site.visit`

**DB table:** `lead_site_visit`  
**Description:** A single site visit appointment event linked to an inquiry. Tracks the property, RM, schedule, status, feedback, and reschedule chain. Renders as calendar events and in the visual timeline HTML.

**Inherits:** `mail.thread`, `mail.activity.mixin`  
**Order:** `scheduled_datetime desc, id desc`

### Core identity

| Field | Type | Required | Stored | Description |
|---|---|---|---|---|
| `name` | `Char` | — | ✓ (computed) | Auto-generated: `"{inquiry name} \| {status name} \| {datetime}"`. |
| `inquiry_id` | `Many2one → leads.new` | ✓ | ✓ | Parent inquiry. `ondelete=cascade`. Indexed. Tracking enabled. |
| `property_base_id` | `Many2one → property.base` | ✓ | ✓ | Property being visited. `ondelete=restrict`. Indexed. Tracking enabled. |
| `assigned_rm_id` | `Many2one → res.users` | — | ✓ | RM responsible for this visit. Indexed. Tracking enabled. |

### Schedule

| Field | Type | Required | Stored | Description |
|---|---|---|---|---|
| `scheduled_datetime` | `Datetime` | ✓ | ✓ | Date and time of the visit. Indexed. Tracking enabled. |
| `scheduled_date` | `Date` | — | ✓ (computed) | Date-only extract of `scheduled_datetime`. Stored. Indexed. |
| `status_changed_on` | `Datetime` | ✓ | ✓ | Timestamp when the current status was last set. Default: `now()`. Indexed. |

### Status

| Field | Type | Required | Stored | Description |
|---|---|---|---|---|
| `status_id` | `Many2one → lead.site.visit.status` | ✓ | ✓ | Current status. `ondelete=restrict`. Indexed. Tracking enabled. Domain: `active=True`. |
| `status_is_scheduled` | `Boolean` | — | ✗ (related) | Mirrors `status_id.is_scheduled_status`. |
| `status_is_rescheduled` | `Boolean` | — | ✗ (related) | Mirrors `status_id.is_reschedule_status`. |
| `status_is_completed` | `Boolean` | — | ✗ (related) | Mirrors `status_id.is_completed_status`. |
| `status_is_cancelled` | `Boolean` | — | ✗ (related) | Mirrors `status_id.is_cancelled_status`. |
| `status_is_no_show` | `Boolean` | — | ✗ (related) | Mirrors `status_id.is_no_show_status`. |
| `status_is_terminal` | `Boolean` | — | ✗ (related) | Mirrors `status_id.is_terminal`. |

### Feedback

| Field | Type | Stored | Description |
|---|---|---|---|
| `feedback_option_id` | `Many2one → lead.site.visit.feedback.option` | ✓ | Selected feedback option. Domain: `[('status_id', '=', status_id), ('active', '=', True)]`. `ondelete=restrict`. Tracking enabled. |
| `feedback_note` | `Text` | ✓ | Free-text feedback note from the RM. Tracking enabled. |

### Reschedule chain metadata

| Field | Type | Stored | Description |
|---|---|---|---|
| `previous_visit_id` | `Many2one → lead.site.visit` | ✓ | The visit this one replaced (set when rescheduled). `ondelete=set null`. Indexed. |
| `root_visit_id` | `Many2one → lead.site.visit` | ✓ | The first visit in the reschedule chain. `ondelete=set null`. Indexed. May be `NULL` on older records — use `previous_visit_id` graph traversal instead. |
| `reschedule_iteration` | `Integer` | ✓ | How many times this chain has been rescheduled. Default: `0`. Indexed. |
| `chain_reschedule_count` | `Integer` | ✗ (computed) | Total reschedule count for the chain this visit belongs to. Not stored. |

### Computed / display

| Field | Type | Stored | Description |
|---|---|---|---|
| `color` | `Integer` | ✗ (computed) | Calendar colour index. green(10)=completed, blue(4)=scheduled, orange(2)=rescheduled, red(1)=cancelled/no-show, yellow(3)=overdue open. |
| `is_overdue_open` | `Boolean` | ✗ (computed) | `True` when the visit is open (scheduled/rescheduled) and `scheduled_datetime < now`. |
| `total_inquiry_visit_count` | `Integer` | ✗ (computed) | Total visit count for the parent inquiry. Not stored. |
| `active` | `Boolean` | ✓ | Soft-delete flag. Default: `True`. Indexed. |

### Denormalized fields

| Field | Source | Stored |
|---|---|---|
| `inquiry_type` | `inquiry_id.inquiry_type` | ✓ |
| `inquiry_phone` | `inquiry_id.phone` | ✓ (indexed) |

---

## Model: `lead.olx.account`

**DB table:** `lead_olx_account`  
**Description:** OLX dealer account credentials and polling state. Passwords are never stored in the database — they are written to and read from `ir.config_parameter` using the key `olx.account.<login>.password`.

**Order:** `sequence, id`

| Field | Type | Required | Stored | Description |
|---|---|---|---|---|
| `name` | `Char` | ✓ | ✓ | Human-readable label (e.g. "Khushi – 8160745862"). Indexed. |
| `login` | `Char` | ✓ | ✓ | OLX phone number used as login. Unique. Indexed. |
| `password` | `Char` | — | ✗ | Write-only UI field. Never stored in DB. `_inverse_password` persists to `ir.config_parameter`. `_compute_password` always returns `False`. |
| `sequence` | `Integer` | — | ✓ | Rotation ordering for polling. Default: `10`. |
| `active` | `Boolean` | — | ✓ | `False` = auto-disabled after 5 consecutive failures. Indexed. |
| `last_fetch_at` | `Datetime` | — | ✓ | Timestamp of the most recent successful OLX API poll. Readonly. |
| `consecutive_failures` | `Integer` | — | ✓ | Number of consecutive API failures since last success. Default: `0`. Readonly. |
| `last_error` | `Text` | — | ✓ | Last error message (truncated to 2048 chars). Readonly. |
| `process_notes` | `Text` | — | ✓ | Audit trail of auto-disable events and manual interventions. Readonly. |

**Constraint:** `_login_uniq` — `login` must be globally unique.

---

## Model: `leads.bde`

**DB table:** `leads_bde`  
**Description:** Business Development Executive registry. BDEs are external partners who bring Ops Sale leads. An RM must be in `allowed_rm_ids` to assign a BDE (unless the BDE is open to all RMs).

**Order:** `name`

| Field | Type | Required | Stored | Description |
|---|---|---|---|---|
| `name` | `Char` | ✓ | ✓ | BDE full name. Indexed. |
| `phone` | `Char` | — | ✓ | Contact phone number. |
| `email` | `Char` | — | ✓ | Contact email address. |
| `active` | `Boolean` | — | ✓ | Soft-delete flag. Default: `True`. |
| `allowed_rm_ids` | `Many2many → res.users` | — | ✓ | RMs permitted to use this BDE. Join table: `leads_bde_allowed_rm_rel`. If empty, all RMs may use this BDE. Domain: `share=False`. |

---

## Model: `whatsapp.response`

**DB table:** `whatsapp_response`  
**Description:** Records a single WhatsApp reply received from a lead for a BQ-scored lead. Tracks the response type, whether it was processed, and carries denormalized lead context for quick display.

**Inherits:** `mail.thread`, `mail.activity.mixin`  
**Order:** `create_date desc`

| Field | Type | Required | Stored | Description |
|---|---|---|---|---|
| `lead_id` | `Many2one → lead.score` | ✓ | ✓ | Parent scored lead. |
| `number` | `Char` | ✓ | ✓ | Phone number the response came from. |
| `response` | `Selection` | ✓ | ✓ | The WhatsApp button/response selected by the buyer. See values below. |
| `response_type` | `Selection` | — | ✓ (computed) | `positive` or `neutral`. Computed from `response`. |
| `response_date` | `Datetime` | — | ✓ | When the response was received. Default: `now()`. |
| `is_processed` | `Boolean` | — | ✓ | Set to `True` by an RM after acting on the response. Default: `False`. |
| `notes` | `Text` | — | ✓ | RM notes about this response. |

**Denormalized fields (stored, from `lead_id`):**

| Field | Source |
|---|---|
| `assigned_rm_id` | `lead_id.assigned_rm_id` |
| `property_address` | `lead_id.property_address` |
| `bhk` | `lead_id.bhk` |
| `predicted_score` | `lead_id.predicted_score` |
| `lead_name` | `lead_id.name` |
| `project_name` | `lead_id.project_name` |
| `current_status` | `lead_id.current_status` |

**`response` selection values:**

| Value | Label | `response_type` |
|---|---|---|
| `yes_going_for_visit` | Yes, going for the visit | `positive` |
| `need_help` | Need Help | `neutral` |
| `yes_visit_done` | Yes, Visit done | `positive` |
| `yes_liked_the_property` | Yes, Liked the Property | `positive` |
| `call_the_expert` | Call the Expert | `neutral` |
| `no_reschedule_visit` | No, Reschedule visit | `neutral` |
| `abhi_call_kare` | Abhi Call Kare | `neutral` |
| `slot_book_kre` | Slot book kre | `positive` |
| `schedule_visit_now` | Schedule Visit Now | `positive` |
| `talk_to_a_property_expert` | Talk to a Property Expert | `neutral` |
| `generic_response` | Generic Response | `neutral` |

---

## Cross-model relationships

```
leads.new (leads_new)
 ├── source_id                → lead.source
 ├── user_id                  → res.users
 ├── property_base_id         → property.base
 ├── property_id              → property.inventory (legacy)
 ├── bde_id                   → leads.bde
 ├── parent_inquiry_id        → leads.new (self-ref)
 ├── child_inquiry_ids        ← leads.new (inverse)
 ├── interest_ids             ← lead.property.interest
 ├── site_visit_ids           ← lead.site.visit
 └── all_associated_properties ↔ property.base (m2m)

lead.score (lead_score)
 ├── assigned_rm_id           → res.users
 └── whatsapp_response_ids    ← whatsapp.response

lead.property.interest (lead_property_interest)
 ├── lead_id                  → leads.new
 └── property_base_id         → property.base

lead.site.visit (lead_site_visit)
 ├── inquiry_id               → leads.new
 ├── property_base_id         → property.base
 ├── assigned_rm_id           → res.users
 ├── status_id                → lead.site.visit.status
 ├── feedback_option_id       → lead.site.visit.feedback.option
 ├── previous_visit_id        → lead.site.visit (self-ref)
 └── root_visit_id            → lead.site.visit (self-ref)

lead.site.visit.feedback.option (lead_site_visit_feedback_option)
 └── status_id                → lead.site.visit.status

lead.source (lead_source)
 ├── category_id              → lead.source.category
 └── default_rm_user_id       → res.users

leads.bde (leads_bde)
 └── allowed_rm_ids           ↔ res.users (m2m via leads_bde_allowed_rm_rel)

whatsapp.response (whatsapp_response)
 └── lead_id                  → lead.score
```

---

## Site visit lifecycle

### Status flags

Each `lead.site.visit.status` record carries boolean semantic flags:

| Flag | Meaning |
|---|---|
| `is_scheduled_status` | Visit is upcoming and active |
| `is_reschedule_status` | Triggers the reschedule write flow (creates new visit, closes old) |
| `is_completed_status` | Visit happened — hard terminal, chain closes |
| `is_cancelled_status` | Visit did not happen — hard terminal (except `code='superseded'`) |
| `is_no_show_status` | Buyer did not appear — hard terminal, chain closes |
| `is_terminal` | Any status that locks the record from further edits |

The special status `code='superseded'` carries `is_cancelled_status=True` (to prevent edit) but is treated as a **chain midpoint**, not a dead end. It is written only by the internal reschedule `write()` flow and must never be set directly by an RM.

### Reschedule flow

When a visit's status is set to one with `is_reschedule_status=True`:

1. A new `lead.site.visit` is created for the same inquiry with `status=scheduled`, carrying `previous_visit_id → old visit`.
2. The old visit is atomically closed with `status=superseded` and the reschedule feedback stored on it.
3. The old visit's `root_visit_id` is inherited so the chain graph remains intact.

### Chain detection in timelines

Timelines use `previous_visit_id` graph traversal — **not** `root_visit_id`:

1. Builds `successor_of[old_id] = newer_visit` from `previous_visit_id` edges.
2. Identifies chain starts (visits with no predecessor in the current set).
3. Walks oldest→newest; splits at hard terminals.
4. Reverses each sub-chain for display (newest first) and sorts by most-recent date.

---

## Lead source architecture

1. `source_id` on `leads.new` is required during lead creation.
2. Portal source is matched via `portal_name` → `lead.source.portal_code`.
3. Portal property is resolved by matching `portal_property_id` against `property.portal.listing.portal_listing_id`.
4. If property resolution fails, assignment uses `lead.source.default_rm_user_id`.
5. If no fallback RM is configured, the system assigns Administrator and records clear process notes.

### Canonical portal mapping

| Input aliases | `portal_code` value |
|---|---|
| `99acres` | `99acres` |
| `housing`, `housing.com` | `Housing.com` |
| `magicbricks`, `magicbricks.com` | `MagicBricks` |
| `olx` | `OLX` |

---

## Related documents

- `custom_addons/leads/CHANGELOG.md`
- `custom_addons/leads/tests/README.md`
- `custom_addons/leads/tests/README.md`