# Escalation Management System

**Module:** `custom_addons/escalations` (new, first-class domain module)
**Branch:** `feature/ml-matching-integration` (off `development_19`)
**Status:** 📋 **PLANNING ONLY — not in the current execution cycle.**

> **Scope discipline.** These documents capture the design so it is not re-derived later. They are **not** an implementation plan, and there is deliberately **no execution-level breakdown** — no task split, no estimates, no sprint mapping.
>
> The current execution cycle is: **get the property-matching model working, plus the Odoo tasks it directly needs.** See [`../ml_matching/README.md`](../ml_matching/README.md).
>
> Work here starts only when that is done and this is explicitly picked up. Two things are already known to gate it: the org-structure dependency (§3, itself parked) and the `deals` module being unmerged (§2.1).

---

## 1. What this is

A **case management system for things going wrong**: a client is unhappy, a listing is failing, a deal is stuck, an RM has not responded. A case is raised, owned, worked against a clock, escalated up a chain if it stalls, closed with a coded resolution, and reviewed in aggregate afterwards.

This is a firm system. It exists to answer, at any moment: *what is broken, who is accountable for it right now, how long has it been broken, and what did we do about it.* Today nothing in Odoo answers that — there is no escalation, complaint or ticket model anywhere in `custom_addons`, and the `helpdesk` addon is Enterprise-only and not available.

**It is not an ML feature.** The Property Matching Model reads one derived fact from this system (*"does this property have an open, qualifying escalation?"*) as one of four inputs to its activation score. That consumer is §8 — a small read contract, deliberately at the edge of the design rather than at its centre.

## 2. Scope — locked

### 2.1 What a case can be about

| Subject | Available now? | Notes |
|---|---|---|
| **Property / listing** | ✅ `property.base` | seller-side: no traction, wrong portal details, owner unhappy with service |
| **Deal in progress** | ❌ **`deals` module is not on `development_19`** | documentation, payment, registration, handover. Lives unmerged on `deal/odoo`. Subject slot designed now, wired when that module merges |
| **RM / internal service failure** | ✅ `res.users` | conduct, unresponsiveness, process breach — a case about a person, not an asset |

**Explicitly out of scope for v1:** buyer lead / inquiry as a case subject. Buyer-side complaints will arrive as *property* or *RM* cases until there is a reason to model them separately.

Because one of three subjects does not exist yet and a fourth is anticipated, the subject is **polymorphic from day one** — see [`01-domain-and-data-model.md`](01-domain-and-data-model.md) §3. Retrofitting polymorphism onto three hard FKs later is a migration; designing it in now is free.

### 2.2 How cases are raised

| Channel | v1 | Notes |
|---|---|---|
| **Internal staff, Odoo UI** | ✅ build | every case has an authenticated raiser |
| **Auto-raised by rules** | ✅ build | SLA breach, 3+ site-visit reschedules (`leads/docs/site-visit-user-stories.md` GAP-03), listing with zero inquiries for N days, mandate near expiry |
| Client via WhatsApp | 🔜 near future | needs `wa_communication`, also **not on `development_19`** (unmerged on `feature/pub-sub`) |
| Client via portal / web form | 🔜 near future | needs public intake, spam handling, identity matching to an existing buyer or owner |

The two future channels are the reason intake is a **separate seam** (`05-intake-channels.md`) rather than logic inside the case model. Every channel produces the same case; only the `source` and the identity-resolution step differ.

### 2.3 Lifecycle: tiered, SLA-driven

A case opens at **L1** with an owner and a clock. Breach of the clock — or a manual push — moves it to **L2**, then **L3**. Escalation is a *level*, and **time is what drives it**, not opinion. Full state machine in [`02-lifecycle-sla-and-tiers.md`](02-lifecycle-sla-and-tiers.md).

### 2.4 Ownership: up the reporting chain

A case routes to the responsible RM, then to that RM's manager, then upward. **This has a hard prerequisite that does not exist yet — see §3.**

## 3. ⚠ Dependency: there is no reporting hierarchy

Tier routing (§2.4) needs to answer *"who is this person's manager?"*. Nothing in the codebase can:

- No module in `custom_addons` depends on `hr`, and there is no `hr.employee` reference anywhere.
- No `manager_id`, `parent_id` or team model on any custom model.
- `property_base.rm_user_id` is a **flat** `res.users` FK.
- `properties.group_property_rm` / `group_property_manager` are flat groups — they say *what* someone may do, not *who they report to*.

**This is a separate, shared concern, not part of this module.** Escalations, lead reassignment and per-team dashboards all need the same structure, so it belongs in its own module rather than inside `escalations` — otherwise every consumer depends on the escalation module to learn its own org chart.

Parked, with the shape and the one decision worth preserving recorded in [`../organization/README.md`](../organization/README.md).

**Consequence for this system:** until it exists, tier routing has no source, so the design assumes a **configured per-category default owner** as the routing target. That fallback is worth having regardless — it covers unassigned listings, RMs who have left, and teams with no lead — and it means the escalation design is not blocked on the hierarchy, only its automatic upward routing is.

## 4. Feature inventory

What "an escalation management system" has to contain. Each maps to a doc.

**Core case handling**
- Raise a case: subject, category, severity, description, evidence attachments
- Deduplication against open cases on the same subject
- Assignment: owner, watchers, reassignment with reason
- Work log: chatter, internal notes vs. client-visible replies, time spent
- Sub-tasks / linked cases (a listing case that spawns a portal-data fix)
- Merge and split
- Close with a **coded resolution** + mandatory note; reopen with reason

**Time and accountability**
- Per-category SLA policies: response target, resolution target
- Business-hours calendars (a Sunday should not burn SLA)
- Pause / hold states that stop the clock, with a reason and a cap
- Tier ladder L1→L2→L3, automatic on breach, manual with justification
- Breach history retained after the fact — a case closed late must still read as late

**Configuration (data, not code)**
- Category taxonomy with owning team + SLA policy per category
- Stage definitions with immutable codes
- Resolution options classified by `category` + `management_signal`, mirroring `lead.site.visit.feedback.option`
- Severity scale and its effect on SLA

**Visibility**
- My cases / my team's cases / breached / at-risk
- Ageing and breach dashboards; per-owner and per-category volume
- Notifications and digests on assignment, breach, tier change, imminent breach

**Governance**
- Full audit trail: who changed what, when, why — and immutable once written
- Permission tiers: raise / work / reassign / close / configure, distinct from each other
- Reason codes on every judgement call, so aggregate review is possible

**Integrations**
- Auto-raise rules from existing signals
- ML activation read contract (§8)
- Later: WhatsApp and portal intake

## 5. Documents

Two are drafted. The rest are **named but not scheduled** — they get written when this system is picked up, not before, so they do not accumulate as stale detail.

| Doc | Covers | Status |
|---|---|---|
| [`01-domain-and-data-model.md`](01-domain-and-data-model.md) | models, polymorphic subject, configuration taxonomy, audit | drafted |
| [`02-lifecycle-sla-and-tiers.md`](02-lifecycle-sla-and-tiers.md) | stages, the state machine, SLA clocks, hold, tier ladder, breach | drafted |
| `03-ownership-and-routing.md` | routing rules, fallbacks, conduct-case conflict of interest | not scheduled — needs [`../organization/`](../organization/README.md) |
| `04-security-and-audit.md` | permission tiers, immutability, non-repudiation, record rules | not scheduled |
| `05-intake-channels.md` | internal UI, auto-raise rules, the seam for WhatsApp/portal | not scheduled |
| `06-views-and-ux.md` + [`wireframes/`](wireframes/) | list/kanban/form, raise and close wizards, dashboards | not scheduled |
| `07-reporting-and-review.md` | ageing, breach, repeat-subject and resolution analytics | not scheduled |
| `08-ml-integration.md` | the read contract for the matching model's activation signal | not scheduled |
| `09-rollout-and-tests.md` | install order, config seeding, migration notes, test matrix | not scheduled |

One routing decision is worth recording now, because it is the kind that gets made wrongly by analogy: **escalation routing must not be load-balanced.** The lead-generation system routes AI-suggested leads to the least-loaded eligible RM (ML repo doc 04 §9) — correct there, wrong here. Lead routing distributes *work* and any eligible person will do; escalation routing fixes *accountability* and one specific person is answerable. Load-balancing a case about Priya's listing onto Rahul because Priya is busy leaves the accountable person with no formal connection to it — and being busy is often a symptom of the problem, not a defence against it.

## 6. Conventions this module follows

Taken from the existing modules so the spec is directly implementable:

- **Immutable codes on config models** — `write()` rejects changes to `code`, as in `lead.site.visit.status` and `lead.site.visit.feedback.option`.
- **Config as data** — stages, categories, resolutions seeded from `data/*.xml`; a new category is a data change, not a deploy.
- **Groups inside `<data noupdate="1">`, record rules outside it** so domain changes apply on upgrade (`properties/security/property_security.xml`).
- **`noupdate` trap handled by migrations** — defaults declared under `noupdate="1"` never reach an already-installed DB, so post-migrate scripts set them idempotently (`properties/migrations/19.0.1.6.0/post-disable_cron.py` is the precedent).
- **Module-local docs** pointer, as `leads/docs/` does; the full specs stay here.
- **Tests tagged and runnable via `run_tests.sh`.**

## 7. Open decisions

1. **The hierarchy** (§3) — parked separately; blocks automatic upward routing only, not the rest of the design.
2. **Business-hours calendar source** — `resource.calendar` (needs `resource`, pulled in by `hr` anyway) or a simple config on the SLA policy.
3. **Are RM-conduct cases visible to the RM?** A case about a person, readable by that person, changes what people write in it. Likely a restricted category with its own record rule.
4. **Client-visible communication in v1?** If a case can hold a client-facing reply, the tone and audit requirements rise sharply. Recommend internal-only for v1 and revisit with the WhatsApp channel.
5. **Retention** — cases are permanent records; confirm nothing here conflicts with how the firm handles owner/buyer PII.
