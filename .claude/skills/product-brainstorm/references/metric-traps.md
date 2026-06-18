# Metric & attribution traps — catalog with worked examples

Read this when tearing down a proposed metric set or designing a new one. Each
trap has a **tell** (how to spot it), the **damage** (why it matters), and the
**fix**. The worked examples are real from the WhatsApp By-RM rebuild; reuse the
*shape* of the reasoning, not the specifics.

## Table of contents
1. Vanity metrics
2. Mislabeled metrics
3. Confounded metrics (the "lead quality" trap)
4. Gameable metrics (proxy vs the real job)
5. Survivorship
6. Single-channel outcome attribution
7. Time-varying ownership / point-in-time attribution
8. The "intractable denominator" reframe
9. The Score-vs-Context test
10. Worked-example technique (how to run the personas)

---

## 1. Vanity metrics
**Tell:** the number is interesting but you can't name the decision it changes.
Counts of activity (messages sent, logins, raw volume) are usually vanity.
**Damage:** fills the screen, dilutes attention from the metric that matters, and
implies "more = better" when it often isn't.
**Fix:** for each metric ask "what does a manager *do* differently when this moves?"
No answer → cut it, or demote to Context as denominator/framing.

## 2. Mislabeled metrics
**Tell:** the label describes a different thing than the formula computes.
**Example:** a column called "Reply rate" that computes *the buyer replied to us*
(`replied / messaged`). A manager reads it as "how diligently my rep replies" — the
opposite of what it measures.
**Damage:** on a performance screen, one mislabel destroys trust in the whole view.
**Fix:** rename to what it is ("Buyer engagement"), or recompute to match the label.
Labels are a contract; honor them.

## 3. Confounded metrics (the "lead quality" trap)
**Tell:** the number moves mostly because of something the actor doesn't control.
**Example — Sneha vs Vikram.** Sneha gets 50 premium, high-intent leads; 40 reply
(80%). Vikram gets 50 recycled cold leads; 12 reply (24%). Score them on buyer-reply
rate and Sneha looks 3× better — but she did nothing special and Vikram may be
grinding harder against a worse pool. The metric measured the *lead allocation* (a
manager's decision), not the rep.
**Damage:** punishes people for inputs they were handed; breeds resentment, gaming,
or learned helplessness.
**Fix:** demote to **Context** (show it, never rank on it) so the manager can see
"Vikram's pool is cold" and judge him on what he controls. Reserve **Scores** for
things mostly within the actor's control.

## 4. Gameable metrics (proxy vs the real job)
**Tell:** there's a cheap action that moves the number without doing the real work.
**Example — Priya vs Arjun.** Priya answers the *first* message in 6 min (96% within
SLA) but abandons 25 of 40 live conversations after a reflexive "Hi, I'll get back to
you." Arjun is slightly slower on first reply (88%) but *sustains* 38 of 40. Score
first-response-only → Priya ranks #1, Arjun gets coached. Exactly backwards: Priya is
leaking warm buyers in the most damaging way (acknowledged, then ignored).
**Damage:** the metric *trains the theater*. At scale you optimize for the hack.
**Fix:** find the signal that tracks the actual job and resists faking. Here:
**follow-through / no-ghost** — did they keep replying once the buyer was engaged?
Nearly impossible to game because you can't fake staying in a real conversation.

## 5. Survivorship
**Tell:** the metric is computed only over the cases that succeeded.
**Example:** "average first-response time" over *answered* chats only. An agent who
cherry-picks easy chats looks fast; the chats they ignored vanish from the stat.
**Damage:** flatters everyone; the failures — the whole point — are invisible.
**Fix:** put the misses in the denominator. Define the unit so an unanswered/abandoned
case still counts (an *obligation* that was missed), attributed to someone. Prefer a
tail statistic (p90) over the mean so the slow cases that actually hurt show up.

## 6. Single-channel outcome attribution
**Tell:** you're about to credit or penalize one channel/team for an outcome that
many things cause.
**Example:** judging WhatsApp responsiveness by deal *conversion*. Conversion is
driven by lead quality, price, property, phone calls, market timing — WhatsApp is one
slice. Two compounding problems: (a) it's permanently unfair to the rep, who can never
move an outcome that's 80% other factors; (b) **column adjacency forces a false causal
read** — put "SLA 95% | conversion 8%" next to "SLA 60% | conversion 20%" and every
viewer draws a line between the columns, no caveat survives the layout.
**Damage:** dishonest by construction; drives wrong coaching.
**Fix:** put the outcome on the screen where the *whole* effort is visible (a
multi-touch view). On the single-channel screen, measure the furthest-downstream
result that channel genuinely *owns* (engagement / handoff), and build a **forward
hook** (stable keys + clean signal) so the multi-touch screen can attribute fairly
later.

## 7. Time-varying ownership / point-in-time attribution
**Tell:** the thing being measured can be reassigned/handed off over its life, and you
only store the *current* owner.
**Damage:** naive attribution blames whoever holds it now for what predecessors did
(or didn't do).
**Fix options, cheapest first:**
- **Actor-based history:** credit whoever actually performed the action, at the moment
  they did it (immune to reassignment — you never ask "who owned it", only "who acted").
- **Real-time snapshot for state:** "what's open/overdue on whose desk *right now*" is a
  fair use of the current owner *because* it's explicitly a now-view.
- **Append-only ownership ledger:** if you truly need fair historical attribution of
  *misses* (which have no actor), record every ownership change as an immutable row so
  you can resolve "who owned X at instant T." This is a real but worthwhile investment;
  be honest that history *before* the ledger starts is best-effort.
- **Clock-transfer rule:** decide explicitly whether handing something off transfers
  responsibility (usually yes — handoff is legitimate load-shedding, and the new owner
  now holds it).

## 8. The "intractable denominator" reframe
When "what's the fair denominator?" has no clean answer (one entity → many
sub-entities → different owners), stop trying to force one. **Change the unit.**
The By-RM move: the unit became the **response obligation** (one per inbound message),
attributed to whoever owned the conversation at resolution-or-breach. Historical
quality metrics became *actor/obligation*-based (no ownership denominator needed);
"what's rotting now" became a *real-time snapshot* by current owner. The impossible
question dissolved because it was the wrong unit. If you're stuck on a denominator,
suspect the unit.

## 9. The Score-vs-Context test
For each metric, ask: **is this mostly within the actor's control?**
- Yes → it can be a **Score** (ranked, drives coaching/accountability).
- No → it's **Context** (shown, never ranked; frames the Scores).

Example split:
- Scores: first-response speed, SLA adherence, follow-through, miss/drop rate.
- Context: buyer-reply rate (pool quality), load (allocation), live backlog.

Render Context visually demoted (grey, labeled) so nobody mistakes it for a verdict.
This single split is usually the most valuable artifact a session produces, because
it's what makes the screen *fair*, and fairness is what makes people trust it instead
of gaming it.

## 10. Worked-example technique (how to run the personas)
The fastest way to make a metric choice concrete is two contrasting characters with
the *same surface numbers but opposite reality*, then show how each candidate metric
ranks them — and what management decision results.

Recipe:
1. Pick the two failure modes you're worried about (fast-but-ghosts vs slow-but-
   sustains; lucky-pool vs unlucky-pool).
2. Give them concrete numbers.
3. Show the leaderboard under metric A, then under metric B.
4. State the *management action* each ranking produces, and which is right.
5. Let the user feel the divergence, then ask the fork.

This converts an abstract argument ("first-response is gameable") into something the
user can see ("you'd put Priya #1 and coach Arjun — backwards"). If you can't build a
divergence for a proposed metric, that's evidence the metric doesn't matter; if you
can, it's a fork worth the user's call.
