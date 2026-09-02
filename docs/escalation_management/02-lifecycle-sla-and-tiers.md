# Escalation Management — lifecycle, SLA and tiers

Part of the [Escalation Management System](README.md). Fields referenced here are defined in [`01-domain-and-data-model.md`](01-domain-and-data-model.md).

---

## 1. Two independent axes

The commonest design mistake in ticketing systems is collapsing these into one column:

| Axis | Question it answers | Field |
|---|---|---|
| **Stage** | what is happening to this case? | `stage_id` |
| **Tier** | how far up the organisation has it travelled? | `tier` |

They are independent. A case can be `in_progress` at L3, or `on_hold` at L1. Combining them produces stages like *"In Progress (Manager)"* and *"On Hold (Manager)"*, and the stage list doubles with every tier — then nobody can answer "how many cases are in progress" without knowing the tier taxonomy.

Kept separate: stage drives the kanban, tier drives accountability and notification.

## 2. Stages

Seeded as data (`escalation.stage`), behaviour carried by flags, never by a hardcoded name list:

| code | Flags | Meaning |
|---|---|---|
| `new` | `is_open` | raised, not yet acknowledged. **Response clock running** |
| `in_progress` | `is_open` | acknowledged and being worked |
| `waiting_internal` | `is_open` | blocked on another team — clock **still running**, because this is our problem |
| `on_hold` | `is_hold`, `stops_clock` | blocked on the client or a third party — clock **paused** (§5) |
| `resolved` | `is_closed`, `requires_resolution` | fixed, awaiting confirmation |
| `closed` | `is_closed`, `requires_resolution` | terminal |
| `cancelled` | `is_cancelled`, `requires_resolution` | raised in error or duplicate. **Not** a success (§`01` §5.3) |

**`waiting_internal` vs `on_hold` is the distinction that decides whether SLA is honest.** Waiting on our own legal team is not the client's problem and must burn clock. Waiting on a document only the client can supply is. Collapsing them into one "waiting" stage lets any delay be reclassified as not-our-fault, and SLA stops meaning anything.

### 2.1 Permitted transitions

```
                ┌──────────────► cancelled
                │
new ──► in_progress ──► resolved ──► closed
         ▲   │   ▲          │
         │   ▼   │          └──► (reopen) ──► in_progress
         │ on_hold                              reopen_count += 1
         │   │
         └───┘
    waiting_internal ◄──► in_progress
```

Rules:
- **`new` cannot jump to `resolved`.** Something claimed fixed without ever being picked up is either not fixed or was never a case. Force it through `in_progress` so `first_response_at` exists.
- **Leaving to `resolved` / `closed` / `cancelled` requires a coded resolution** (`requires_resolution` on the stage).
- **Reopen is a first-class transition,** not a manual stage edit — it increments `reopen_count` and appends an event. Three reopens is a signal about the *resolution*, not the case.
- **`cancelled` needs a resolution too**, because "raised in error" is itself a finding: a category people mis-file into is a category with a naming problem.

Transitions are validated against a table keyed on stage **codes**, so a renamed stage cannot break the machine.

## 3. Tiers

| Tier | Owner | Reached by |
|---|---|---|
| **L1** | the responsible RM (or the category's default owner) | every case opens here |
| **L2** | that RM's manager | SLA breach, tier dwell timeout, or a manual push |
| **L3** | leadership | same, from L2 |

Three properties that matter:

- **Tier only ever goes up automatically.** De-escalation is possible but is a manual, justified act — otherwise a case ping-pongs as clocks recompute.
- **A tier change reassigns `owner_id`** and appends an event carrying both the old and new owner. Accountability is never ambiguous: exactly one person owns the case at any moment.
- **Tier is sticky across stages.** Putting an L3 case on hold and resuming it does not send it back to L1; the organisation already knows about it.

Auto-push is blocked when the target owner cannot be resolved — see `03-ownership-and-routing.md` and the hierarchy blocker in README §3. In that state the case stays at its tier, is flagged `routing_failed`, and lands on an exception list. **It must never silently stop escalating**; a routing gap that presents as a quiet case is the worst outcome here.

## 4. SLA clocks

Two clocks per case, from the snapshotted policy (§`01` §4.2):

| Clock | Starts | Stops | Breach means |
|---|---|---|---|
| **Response** | `opened_at` | `first_response_at` | nobody picked it up |
| **Resolution** | `opened_at` | `closed_at` | it was not fixed in time |

### 4.1 Deadlines are stored, breach is computed

`response_deadline` and `resolution_deadline` are **stored** — they are the output of a business-hours calculation over the calendar, which is expensive and must be identical every time it is read.

`is_breached` / `is_at_risk` are **computed with `search` methods, never stored, never cron-maintained** — the reasoning is in §`01` §4.1, and it is the single most important mechanical decision in this system: a stored breach flag that a failed cron did not set looks exactly like a case that is fine.

`breached_at` is stored, once, the first time the sweep observes a breach — because after a hold or a tier change moves the deadline, the moment of crossing is no longer derivable.

### 4.2 Business hours

Deadlines are computed over a calendar, not by adding wall-clock hours. A high-severity case raised 18:00 Saturday with an 8-hour target is not breached by Sunday morning.

Calendar source is open (README §7.2). Whichever is chosen, the calendar is **snapshotted with the policy** — a case must not silently re-derive its deadline because someone edited working hours.

### 4.3 Severity compresses the target

Severity is the human's assertion of how bad it is; it multiplies the category's base target:

| Severity | Multiplier | 24h base becomes |
|---|---|---|
| `low` | 2.0 | 48h |
| `medium` | 1.0 | 24h |
| `high` | 0.5 | 12h |
| `critical` | 0.25 | 6h |

**Severity is the one number a human sets that directly shortens a clock** — which makes it the inflation surface, exactly as escalation weight was on the ML side. Controls:

- **Raising severity after creation is a wizard with a reason**, and it appends an event. Lowering it is too — quietly downgrading a case is how a breach gets avoided without the problem being solved.
- **`critical` is restricted** to a group, and its use is reported per person per month (§`07`). A `critical` that everyone can set becomes the default within a quarter.
- **Deadlines recompute from `opened_at`, not from the moment of change.** Otherwise raising severity late would *extend* a nearly-breached case, which is backwards.

## 5. Hold — pausing the clock

Only `on_hold` (`stops_clock`) pauses. On entry: `hold_since` is set with a required `hold_reason_id`. On resume: elapsed time is added to `hold_total_seconds`, both deadlines shift forward by that amount, and an event records the pause with its reason.

Three guards, because hold is the obvious way to make a breach disappear:

| Guard | Rule |
|---|---|
| **Coded reason, always** | `escalation.hold.reason` is a config model, so holds are countable by reason — an aggregate nobody can argue with |
| **A cap** | total hold beyond `max_hold_hours` stops extending deadlines. The case can stay on hold; the clock stops being forgiven |
| **Hold does not pause tier dwell** | a case parked at L1 for three weeks still escalates. Otherwise hold becomes a way to keep a case invisible |

**Hold time is retained separately and reported separately.** "Resolved in 4 days, 3 of them on hold" is the honest statement; folding hold into elapsed time hides where the delay was, in either direction.

## 6. The SLA sweep

One cron, `escalation_cron.xml`, every 15 minutes. It **performs side effects only** — it never computes state that a read could compute:

```python
def _cron_sla_sweep(self):
    """
    Act on cases whose clocks have moved. Idempotent: every action is guarded
    by the state it produces, so a missed run catches up and a double run is
    a no-op. Never sets `is_breached` - that is computed (see 01 §4.1).
    """
    now = fields.Datetime.now()

    # 1. Record first observation of breach (guard: breached_at not yet set)
    newly = self.search([("is_breached", "=", True), ("breached_at", "=", False)])
    newly.write({"breached_at": now})
    newly._log_events("breached", is_system=True)

    # 2. Notify at-risk (guard: at_risk_notified_at)
    # 3. Auto-push tier where dwell exceeded (guard: tier + tier_changed_at)
    # 4. Digest to owners and L2/L3 watchers
```

> **The division of labour, stated once:** *state is derived, side effects are performed.*
>
> A missed sweep therefore costs **late notifications** — it does not cost correctness. Breach reporting, dashboards and the ML read all go through the computed predicate and are right the instant they are read, whether or not the cron ran. Only the emails are late.
>
> This is the whole reason for the split. Had breach been a stored flag, a failed sweep would corrupt every downstream number silently and permanently.

Idempotency is not optional: crons get retried, run late, and run twice after a restart. Every action above is guarded by the state it produces.

## 7. Notifications

| Event | Who | Channel |
|---|---|---|
| Assigned to you | owner | Odoo inbox + activity |
| At risk (75% of target elapsed) | owner | inbox, once — guarded, not per sweep |
| Breached | owner + next tier | inbox, once |
| Tier changed | new owner (action) + previous (information) | inbox |
| Reopened | last closer + current owner | inbox |
| Daily digest | owners with open cases; L2/L3 with breached | one message, not per case |
| `routing_failed` | administrators | exception list |

**Every notification is once-only, guarded by a timestamp field.** A sweep every 15 minutes with unguarded notifications sends 96 emails a day per breached case, and the response is to filter the sender — after which the system has no notification channel at all.

## 8. Worked example

`ESC/2026/00417` — owner unhappy that a listing has had no site visits in six weeks.

| When | What | Stage | Tier | Owner | Clock |
|---|---|---|---|---|---|
| Mon 10:00 | raised, internal UI, category `listing_no_traction`, severity `medium` | `new` | L1 | RM Priya | resolution due Wed 10:00 (24 business hours) |
| Mon 11:20 | Priya acknowledges | `in_progress` | L1 | Priya | `first_response_at` set — response clock met |
| Mon 16:00 | needs revised photos from the owner | `on_hold` (`awaiting_client`) | L1 | Priya | paused |
| Wed 09:00 | photos received | `in_progress` | L1 | Priya | +41h hold → due Fri 03:00 |
| Wed 12:00 | tier dwell at L1 exceeded (72h) | `in_progress` | **L2** | Priya's manager | deadline unchanged; hold does not pause dwell (§5) |
| Fri 03:00 | resolution deadline passes | `in_progress` | L2 | manager | `breached_at` = Fri 03:00, **stored once** |
| Fri 14:00 | photos live, portal refreshed, owner called | `resolved`, resolution `relisted_with_new_media` (`counts_as_success = True`) | L2 | manager | closed **late** |

Reads afterwards as: resolved successfully, 11 hours late, 41 of the elapsed hours on client hold, escalated once. **Every one of those five facts is separately visible** — which is the point of keeping stage, tier, hold and breach on their own axes instead of in a single status column.

## 9. Open decisions

1. **Tier dwell values per tier** — 72h at L1 is a placeholder. Needs the firm's actual expectation.
2. **Does `resolved` auto-close after N days without objection?** Convenient, and it quietly converts "nobody checked" into a success. If added, it needs its own resolution code so it is distinguishable.
3. **`max_hold_hours`** — value, and whether it differs by category.
4. **Who may set `critical`** — the restricted group's membership.
5. **Should breach at L3 trigger anything further?** There is no L4. Probably a standing report rather than a notification, since the alternative is an alert with nowhere to go.
