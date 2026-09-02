# Lead form — complete surface inventory and redesign disposition

**Companion to:** [`03-rm-assist-integration.md`](03-rm-assist-integration.md)
**Figma:** [RM Assist (Mode 1)](https://www.figma.com/design/HGQW9SgUL37RmL8apoPsiD) — built frames listed in §7, pending frames specced in §8
**Source of truth for the current behaviour:** `leads/views/new_portal_lead_views.xml`, `leads/views/lead_site_visit_wizard_views.xml`, `custom_addons/wa_communication/static/src/lead_tab/` (on `feature/pub-sub`)

> **Why this document exists.** The redesign has to preserve every job the current form does. This enumerates every field, button, tab, banner and wizard in the live form — read from the XML, not from the screenshots — and states what happens to each. Nothing is dropped silently; anything removed is named with a reason.

---

## 1. Correction to the first design pass

**I demoted the most-used control in the product.** The first Figma pass replaced the header with a four-step pipeline, on the assumption that the two statusbars were redundant chrome. They are not — `current_status` is what RMs change constantly, and the redesign made it *harder* to reach.

The underlying defect in the current UI is sharper than "two statusbars", and it explains the behaviour:

```xml
<field name="current_status" widget="statusbar"
       statusbar_visible="lead,details_shared_of_property,requirement_closed"/>
```

**The header statusbar exposes 3 of the 17 values.** So for 14 of 17 outcomes the header is useless and the RM must go into the *Primary Inquiry* tab and use the dropdown. The header control isn't ignored because RMs prefer dropdowns — it's ignored because it cannot express the answer.

Fixed in Figma: one status control, in the header, reaching all 17 values, grouped into six sets, keyboard-first (`S` to open, type to filter, `↑↓ ⏎` to commit). Frame `Status picker — all 17 values, grouped`.

### 1.1 The grouping

| Group | Values | Why grouped |
|---|---|---|
| **Trying to reach** | Ringing · Busy · Call Back Later · Switched Off | the commonest outcome of a dial, so it sorts first |
| **In conversation** | Lead · Details Shared of Property · Detail Shared and Interested for Site Visit | the buyer is engaged |
| **Site visit** | Site Visit Scheduled · Rescheduled · Site Visit Done | each **implies an action** — §1.2 |
| **Not moving forward** | Option Not Matching Requirements · Budget Not Sufficient · No Requirements · Property Sold Out · Requirement Closed | five ways of "no", kept distinct because they are different reasons |
| **Bad contact** | Number Not in Use / Wrong Number | a data problem, not a sales outcome |
| **Other** | Other | |

The current field order opens with `busy, lead, ringing` — declaration order, not call order.

### 1.2 Statuses that imply an action offer it inline

Picking **Site Visit Scheduled** or **Rescheduled** opens the visit wizard in the same gesture. **Site Visit Done** asks for the visit feedback. Today these are separate steps, which is how a lead ends up marked `site_visit_scheduled` with no `lead.site.visit` record behind it — and that divergence is invisible until someone reads both.

---

## 2. Header

| Element | Current | Disposition |
|---|---|---|
| `state` statusbar (`new` / `assigned` / `failed`), manager-only | competes visually with `current_status` | **Kept as a badge** next to the buyer name. It is a system fact, not a sales stage, and it is manager-only |
| `current_status` statusbar (RM), 3 of 17 values | the defect in §1 | **Replaced** by the grouped status control |
| **Schedule a Visit** (`btn-primary`, RM) | | kept, primary |
| **Update Latest Visit** (`btn-secondary`, hidden when no `latest_site_visit_id`) | | kept, secondary, same conditional |
| **Recommend Property** (`btn-secondary`, hidden when `inquiry_type != 'primary'`) | | kept, secondary, same conditional — opens the redesigned panel |
| Send message / Log note / Activity | chatter actions | kept, moved into the Activity card composer |
| Record pager `73 / 80` | | kept |

**Derived "Stage" label** sits under the status control (*Stage: In conversation*), giving the at-a-glance funnel position the 3-value statusbar was trying to provide, without pretending the field has three values.

---

## 3. Identity block

| Field | Disposition |
|---|---|
| `name` | Buyer name, largest type on the record |
| `phone` + `action_whatsapp_with_copy` button | Phone with **Call · WhatsApp · Copy** as three real buttons. The WhatsApp action keeps its copy-message behaviour |
| `email` | kept, secondary line — frequently empty in practice |
| `source_id` (required) | Details card. **Required on create** (§6) |
| `is_portal_source` (invisible) | stays invisible |
| `portal_property_id` (when portal source) | Details card, conditional — unchanged |
| `inquiry_type` (readonly) | becomes the **banner** (§4), not a field. It was shown three times |
| `parent_inquiry_id` (readonly, recommended only) | in the banner: *"Recommended from → Rajesh Zala"*, as a link |
| `create_date` (readonly) | meta line under the name |

---

## 4. The two banners

```xml
<div class="alert alert-info"    invisible="inquiry_type != 'primary'">Primary Inquiry</div>
<div class="alert alert-warning" invisible="inquiry_type != 'recommended'">Recommended Inquiry</div>
```

A full-width alert saying "Primary Inquiry" on the majority of records is chrome — it consumes the most valuable strip of the page to tell the RM the default case.

- **Primary:** no banner. It is the default; absence carries it.
- **Recommended:** a **compact inline strip** naming the parent — *"Recommended inquiry · from Rajesh Zala · offered by Anand Maurya"* — because here the relationship is genuinely load-bearing, and the parent link is what the RM needs.

Also removed on the recommended variant, matching current behaviour: the **Recommend Property** button and the **Recommended Inquiries** tab.

---

## 5. Tabs

Four tabs today: *Primary Inquiry*, *Recommended Inquiries*, *Visit Timeline*, *WhatsApp Activity*. Kept as four, renamed and re-scoped — the earlier plan to merge everything into one Activity thread was wrong for the visit and WhatsApp surfaces, which are working tools, not history.

| Tab | Renamed | Notes |
|---|---|---|
| Primary Inquiry | **Overview** | "Primary Inquiry" duplicated the banner and the field |
| Recommended Inquiries | **Recommended · n** | count in the label, hidden on recommended records |
| Visit Timeline | **Visit timeline · n** | §8.1 |
| WhatsApp Activity | **WhatsApp · n replies** | §8.2 |

### 5.1 Overview tab — field-by-field

| Field | Disposition |
|---|---|
| `user_id` (Assigned RM) | Details card. Editable — reassignment happens here |
| `last_reassignment_batch_id` (mgr, when set) | Details card, conditional, manager-only — unchanged |
| `property_base_id` | **Interested-in card**: full name, never truncated, with price / BHK / locality and *Schedule a visit* / *View listing* |
| `base_property_tag` | **Removed from the reading path.** A machine slug (`202-tirthbhumi-apartment-maninagar-mar26`) shown as a user-facing field. Still searchable, still in the search view, and available via *View listing* |
| `current_status` | Now the header control (§1). Removing the duplicate is the point |
| `latest_site_visit_id` (readonly) | Summarised on the Visit timeline tab and in the *Update latest visit* button's presence |
| Muted div *"Use Schedule a Visit and Site Visit History for all visit updates."* | **Deleted.** An instruction occupying a field slot is a design failure; the buttons it describes are adjacent |
| `remarks` | **Kept and enlarged.** Currently a cramped bottom-left field; becomes a proper note area in the Activity composer |
| `base_property_location` | folded into the Interested-in card |
| `base_property_link` (url widget) | becomes the *View listing* button |
| `base_property_bhk` | folded into the Interested-in card |
| `base_property_city` | folded into the Interested-in card |
| `base_property_owner_name` | **Behind a permission-gated "Owner details" disclosure.** Seller PII does not belong open on a buyer's record |
| `is_ops_sale_lead` | Details card |
| `bde_allowed_ids` (invisible) | stays invisible — it is the domain source for `bde_id` |
| `bde_id` (required when ops-sale, domain `bde_allowed_ids`) | Details card, conditional and required exactly as now. **The domain must stay** — it is what stops a lead being assigned to a BDE the RM is not authorised for |

**Nothing in the Overview tab is lost.** Six read-only property mirrors become one property card; the slug and the instruction div go; the owner moves behind a disclosure.

### 5.2 Recommended tab

`child_inquiry_ids` list: `name`, `property_base_id`, `user_id`, `current_status`, `state`.

Redesign: one card per recommended property showing the property, the status, the RM, and **when it was offered** — plus, once §8 of the integration doc lands, whether the model suggested it and at what rank. This becomes the surface where AI-influenced recommendations are visibly distinguishable from RM-originated ones.

---

## 6. Manual lead creation

The same form creates leads by hand, and creation has different needs from editing: nothing to read, one thing to do, speed matters.

**Create mode shows only what is needed to save:**

| Field | Why |
|---|---|
| `name` | required |
| `phone` | the identity key. **Duplicate check on blur** against `(phone, property_base_id)` — the recommend wizard already enforces this pair, so the form should too, before the user finishes typing |
| `source_id` | required today |
| `property_base_id` | what they enquired about |
| `user_id` | defaults to the current user |
| `is_ops_sale_lead` → `bde_id` | revealed only when ticked, required when it is |

Email, portal id and remarks stay behind *"Add more details"*.

**On save:** land on the created record. If the outcome below was left untouched, focus the status control — the next thing that happens is a call and then a status change.

### 6.1 Call outcome at save time

An earlier pass refused to ask for status at creation, reasoning that classifying an uncalled lead invites a meaningless answer. That was right about **requiring** it and wrong about the common case, and prod says so unambiguously.

**Evidence** (validated 2026-07-31, read-only; `source_type = 'manual'`, n = 8,415 of 130,406 leads):

| Measure | Result |
|---|---|
| Manual leads whose status changes **within 5 minutes** of creation | **89.3%** (5,461 / 6,113 that ever change) |
| — within 1 hour | 91.8% |
| Manual leads still sitting at the default `lead` | **0.4%** (37) |
| Most common **first** status set after creation | **`site_visit_scheduled` — 70.5%** |

The save-then-reopen round trip is not an edge case; it is what manual creation *is*. The RM saves, re-opens the record, changes the status, and in 70% of cases then opens the visit wizard — three navigations for facts they held at the moment of typing.

**Manual leads are a different population from portal leads** and must not be laid out like them:

| `current_status` | All leads | Manual only |
|---|---|---|
| `site_visit_scheduled` | 9.0% | **43.2%** |
| `site_visit_done` | 3.9% | **24.7%** |
| `details_shared_of_property` | 10.6% | 15.2% |
| `option_not_matching_requirements` | 12.8% | 9.1% |
| `ringing` | 19.1% | **0.6%** |
| `lead` | 24.7% | **0.4%** |

A manual lead is a record of a conversation that already happened; a portal lead is an inbound enquiry waiting to be worked. Half the "couldn't reach them" ladder that dominates portal leads is statistical noise here.

So the create form ends with **"How did the call go?"** — offered, never required, with *"Haven't called yet"* pre-selected (→ `current_status = lead`, the existing default). Skipping it costs one glance.

**Layout follows the measurement.** Five chips carry 98% of first-set statuses and sit on one row, `site_visit_scheduled` rendered largest; the remaining 2% — the whole couldn't-reach group plus the not-moving-forward tail — sits behind an *"Other outcomes"* disclosure. **All 17 values stay reachable**, grouped as in the record-mode picker (§1.1), with one deliberate exception: `rescheduled` presupposes a visit already on the record, so offering it at create would either fail on save or silently invent a prior visit.

**Nothing that writes a row is ever pre-selected.** Defaulting to the 70% answer would be faster and would fabricate site visits on every mis-save. The default stays `lead`, which writes nothing.

**The follow-up is the point, not the status.** Every outcome an RM realistically picks after a call carries a second fact knowable only at that moment. Today it is lost, or buried in `remarks`:

| Outcome chip | `current_status` | Revealed inline | What save writes |
|---|---|---|---|
| Haven't called yet | `lead` | — | the lead only |
| Ringing · Busy · Switched off | `ringing` / `busy` / `switched_off` | — | the lead only |
| Call back later | `call_back_later` | when: 2h · this evening · tomorrow 11am · pick | `mail.activity` on the lead, assigned to the creator |
| Wrong number | `number_not_in_use_wrong_number` | bad-contact warning | no assignment; number excluded from matching |
| Shared details | `details_shared_of_property` | — | the lead only |
| Interested in a visit | `detail_shared_and_interested_for_site_visit` | note only | lead opens with *Schedule a visit* as next best action |
| Visit scheduled | `site_visit_scheduled` | date + time chips, taken slots struck through, *More options…* → full picker | `lead.site.visit`, status **scheduled**, plus the calendar activity |
| Already visited | `site_visit_done` | past date + `feedback_site_visit_done` (top 5 + all 12) | `lead.site.visit`, status **completed**, dated in the past, flagged *visited from outside* |
| Not matching · Budget short | `option_not_matching_requirements` / `budget_not_sufficient` | budget band · BHK · locality chips | an **asserted** requirement (see below) |
| No requirement · Requirement closed · Other | `no_requirements` / `requirement_closed` / `other` | reason chips | `feedback_general` |
| Property sold out | `property_sold_out` | flag notice | a sold-out **flag** for inventory to confirm — the listing itself is never changed from a lead form |

A live **"Saving will create, in one transaction"** summary sits above the footer, and the primary button renames itself (*Create & schedule visit* / *Create & log visit*) so the RM knows what the one click does before making it.

**Four rules this has to hold to:**

1. **One save, one transaction.** Lead, visit, activity, feedback and requirement commit together or not at all. A visit row that survives a failed lead create — or a lead claiming a visit that was never written — is worse than two manual steps.
2. **Odoo does not track a value set at create.** `tracking=True` logs *changes*, so a lead created directly as `site_visit_scheduled` would have no funnel entry at all; it would look like it was born there. A non-default outcome therefore posts an explicit chatter entry — *"Created with call outcome: Site Visit Scheduled — asserted by \<user\>"* — so the funnel timeline and the ML's status history stay honest.
3. **Asserted beats inferred, and stays labelled.** A requirement heard on the call is stored as asserted and outranks anything derived from inquiry history — the same distinction the requirement card makes, and the same reason the feature spec keeps three-state missingness instead of collapsing *unknown* into *absent*.
4. **These leads are organic.** No provenance flags, and the training-exclusion rules for model-created leads do not apply to them.

**Re-measure before build, and after.** The chip set above is fixed to a distribution measured on 2026-07-31; the mix drifts, and the block itself will change it (a status that is one tap instead of three navigations gets used more). Re-run before implementation and again 90 days after release — if a tail chip climbs above ~3% of first-set statuses it earns the front row, and a front-row chip that falls below it goes behind the disclosure. Queries used:

```sql
-- population comparison: manual vs all
SELECT current_status, count(*) AS n,
       count(*) FILTER (WHERE source_type = 'manual') AS n_manual
FROM leads_new GROUP BY 1 ORDER BY 2 DESC;

-- the decisive one: first status set after creation, and how soon
WITH fst AS (
  SELECT DISTINCT ON (m.res_id)
         m.res_id,
         COALESCE(mtv.new_value_char, mtv.new_value_text) AS ns,
         mtv.create_date AS ts
  FROM mail_tracking_value mtv
  JOIN mail_message m      ON m.id = mtv.mail_message_id
  JOIN ir_model_fields f   ON f.id = mtv.field_id
  WHERE f.model = 'leads.new' AND f.name = 'current_status'
  ORDER BY m.res_id, mtv.create_date
)
SELECT fst.ns AS first_status_set, count(*),
       count(*) FILTER (WHERE EXTRACT(EPOCH FROM (fst.ts - l.create_date))/60 < 5) AS within_5min
FROM leads_new l JOIN fst ON fst.res_id = l.id
WHERE l.source_type = 'manual'
GROUP BY 1 ORDER BY 2 DESC;
```

Note the model name is `leads.new` (not `leads.new.inquiry`) and the table is `leads_new`; tracking rows carry the **label**, not the code (`'Site Visit Scheduled'`, not `site_visit_scheduled`).

**One caveat on the 5-minute figure.** It measures the first *tracked change*, which excludes leads created and never touched again — those are the 0.4% still at `lead`, so the direction of the bias is known and small. It also cannot distinguish "RM already knew" from "RM called immediately after saving"; both are served by the same design, since the block is offered rather than required.

**Duplicate handling is the real risk.** `action_create_recommended_inquiry` raises *"An inquiry already exists for this buyer and property"* — as a `ValidationError` after the fact. In create mode this should surface **as the phone is entered**, with the existing lead offered as a link, so the RM opens it instead of fighting a save error.

---

## 7. Built in Figma

| Page | Frames |
|---|---|
| **00 · Principles & Foundations** | principles, 14-row problem→fix teardown, token swatches, type ramp, match-band legend |
| **01 · Lead Form** | Desktop 1440 (status control corrected, header actions, tab bar) · Mobile 390 · lead-form rationale card · **Status picker — all 17 values, grouped** |
| **02 · Recommend Panel** | six states + per-state annotation cards |

## 8. Specced, not yet built — Figma writes hit the Starter-plan MCP limit

These are fully specified below so they can be built as soon as writes are available.

### 8.1 Visit timeline tab

**The current tab overstates activity.** It numbers every reschedule as its own visit, so a buyer with three appointments that each moved reads as `#17`. Three appointments and ten reschedules is a very different story from seventeen visits — and it is the reschedule count, not the visit count, that is the management signal (`leads/docs/site-visit-user-stories.md` GAP-03 wants an alert at ≥ 3).

**Redesign — the appointment thread is the row:**

- **Summary strip:** `3 appointments · 1 completed · 2 upcoming · 10 reschedules · 3 properties · 1 RM`
- **Scope as a segmented toggle** — *This inquiry* / *All inquiries for this phone* — replacing two stacked tables and the paragraph that explained the difference (`inquiry_timeline_html` and `overall_timeline_html`)
- **Thread card** per appointment: coloured left band (thread identity), current date/time, status pill, property named **once**, RM, `Open ↗`
- **Reschedules collapsed inside:** *"Moved 4× · first booked 29 Jun 2026"*, expanding to the move list. The current UI repeats the property on all five rows
- **Feedback shown in full**, not truncated into a narrow column — it is what the graded reward is built from, so it earns the width
- Legend: Completed · Scheduled · Rescheduled · No show · Cancelled
- Actions: *Schedule another visit* · *Open full visit list* (preserving `action_view_site_visits` and `action_view_all_phone_site_visits`)
- A reschedule count ≥ 3 renders as a warning on the thread

### 8.2 WhatsApp Activity tab

From `wa_communication/static/src/lead_tab/wa_lead_tab.xml` (unmerged on `feature/pub-sub`). Every state below exists in that widget and must appear in the mockup:

| State | Design |
|---|---|
| Loading | skeleton, not a spinner |
| Error | inline, not a dialog |
| **No conversation yet** | *"Send a template message to start the conversation. Templates work even before the customer messages you first."* + **Send Template** primary |
| Active chat | message list, inbound left / outbound right, quick-reply buttons rendered as buttons, read ticks, timestamps |
| **Segment selector** | `DISCUSSING [property ▾]` — which inquiry/property this thread is about (`activeSegmentLabel`, `activeInquiryId`, `activePropertyId`), plus `segmentSuggestion` when the system infers a different one |
| **Window badge** | `windowState` + `windowExpiresAt`. The 24-hour rule is a hard constraint, so it gets a persistent badge and a **countdown** when open — not just a red pill once it is too late |
| **Window closed** | composer disabled with the reason stated (*"Window closed — use Send Template to reach this contact"*) and Send Template promoted |
| **Claim bar** | unassigned → **Claim** · pending → hourglass + message · assigned elsewhere → *Assign Conversation* |
| **Handover banner** | requester name, optional note, **Accept** / **Decline** |
| Send gate | `sendGateReason` shown as text next to a disabled composer — never a silent no-op |
| Sidebar | Assigned to · **STATS** (Sent, Delivered %, Read %, Replies) · **ACTIONS** (Send Template, Assign Conversation, Open in Interakt) |
| Template picker | modal, searchable, with a preview of the rendered message |

**Design decisions to carry in:** the window countdown belongs next to the composer where the decision is made, not only in the sidebar; the segment selector is the tab's most confusing element and needs an explicit label (*"This conversation is about"*); and stats are diagnostic, so they sit in the rail rather than above the messages.

### 8.3 Schedule a Visit wizard

Current fields: `inquiry_id` (ro), `property_base_id` (ro), `assigned_rm_id`, `scheduled_datetime`, `status_id`, `feedback_option_id`, `previous_visit_id` (when `status_id.is_reschedule_status`), `feedback_note`.

Redesign: buyer and property as a **context header**, not two read-only fields. Date and time as the first and largest input, with **quick chips** (Today · Tomorrow · This weekend) and common slots — RMs book round hours. `status_id` defaults to `scheduled` and is hidden unless changed. `feedback_option_id` is **hidden at creation** — a visit that has not happened has no feedback, and offering the field invites nonsense. `previous_visit_id` appears only for reschedule statuses, exactly as now, and is pre-filled with the latest visit.

### 8.4 Update Latest Visit wizard

Current fields: `visit_id` (ro), `inquiry_id` (ro), `property_base_id` (ro), `assigned_rm_id` (ro), `current_status_id` (ro), `status_id`, `scheduled_datetime` (required when `is_reschedule`), `feedback_option_id`, `feedback_note`.

The current dialog is titled **"Odoo"**, shows four read-only fields before the two that matter, and hides the outcome behind a select. Redesign: title *"Update visit — Tirthbhumi Apartment, 18 Jul 6:00 PM"*; the **outcome as large choice buttons** (Completed · Rescheduled · No show · Cancelled) since there are only four realistic answers; date/time revealed only for Rescheduled (matching `is_reschedule`); then feedback, **grouped by `category` and coloured by `management_signal`** so a loss reason reads as a loss reason. Notes optional and last.

### 8.5 Recommended-inquiry variant + `lead.property.interest`

The interest form (`view_lead_property_interest_form`) has its own statusbar and an *Update Status* group with `current_status`, `site_visit_date` (when scheduled), `feedback_general` / `feedback_site_visit_done` (mutually exclusive by status), `remarks`. Its redesign reuses the §1 status control and the §8.4 feedback grouping, so a recommended property is updated with the same gesture as a primary inquiry.

---

## 9. Nothing removed without a reason

The complete list of what the redesign drops, so it can be challenged:

| Removed | Reason |
|---|---|
| `state` statusbar as a statusbar | becomes a badge; it is a system fact, not a sales stage, and manager-only |
| `current_status` statusbar (3 of 17) | replaced by a control that reaches all 17 |
| "Primary Inquiry" banner | tells the RM the default case, in the most valuable strip of the page |
| `base_property_tag` field | machine slug; stays searchable and reachable via the listing |
| Five read-only property mirror fields | consolidated into one property card that shows the same facts |
| `base_property_owner_name` | seller PII on a buyer record; moves behind a permission-gated disclosure |
| Muted instruction div | instructions in a field slot; the buttons it names are adjacent |
| `latest_site_visit_id` as a form field | summarised on the Visit timeline tab, where the visits are |

Everything else in §2–§5 is preserved, including every conditional (`invisible`, `required`, `groups`, and the `bde_id` domain).
