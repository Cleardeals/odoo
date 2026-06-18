---
name: product-brainstorm
description: >
  Run a rigorous, senior-Big-Tech-PM-style product brainstorm BEFORE building any
  feature, dashboard, metric, KPI, scorecard, leaderboard, report, or analytics
  view — so the team ships something that drives a decision instead of a vanity
  system nobody acts on. Pressure-tests two things together: WHAT to measure and
  HOW to represent it. Challenges vanity / mislabeled / confounded / gameable
  metrics, enforces fair attribution (score-vs-context, point-in-time ownership,
  the single-channel fallacy, survivorship), uses contrasting worked examples to
  expose what a choice does, and locks decisions one fork at a time via
  AskUserQuestion. Use this whenever the user wants to design or rethink a
  dashboard / KPI / leaderboard / scorecard / report / analytics screen, or says
  "brainstorm", "grill me", "what should we measure", "is this metric fair/useful",
  "how should we represent this", "plan this screen", "this feels too simple", or
  is otherwise about to build measurement or analytics. Trigger even if the user
  never says the word "brainstorm" — any "design a metric / dashboard / scorecard /
  report" request qualifies. Don't skip this and jump straight to building; a
  thirty-minute grilling here prevents a useless system later.
---

# Product brainstorm — grill the idea before you build it

The purpose of this skill is to stop you from confidently building the wrong thing.
Most dashboards, scorecards, and metrics that get built are **vanity** (they look
busy but drive no decision), **unfair** (they judge people on things they don't
control), or **misleading** (they invite a false read). The cost of that isn't
just wasted build time — a metric that goes on a wall changes how people behave,
so a bad metric actively trains bad behavior at scale.

So before writing code for anything measurement-shaped, run a real product
session: act as a sharp senior PM, pressure-test the idea (theirs *and* yours),
and only converge once the decisions are honest and locked. The user explicitly
invited this with phrases like *"grill me", "brainstorm with me", "don't take my
words as-is"* — take that seriously. Capitulating to the first idea is the failure
mode; so is steamrolling with your own. The job is to think *with* them, hard.

## What a good session produces

By the end you should have, written down:

1. **A teardown** of the existing/proposed thing — every weak metric named, with
   *why* it misleads.
2. **A locked decision list** — each fork resolved, with the reasoning, so nobody
   re-litigates it later. (These belong in a plan file and/or a memory.)
3. **A metric set split into Scores and Context** (see below) — and a clear
   statement of what each metric drives and who acts on it.
4. **A representation plan** — how it's shown, glanceably, with help affordances.
5. **Forward hooks** for the valuable-but-out-of-scope ideas, so nothing good is
   lost and nothing dishonest is shipped.

If you can't say what *decision* a metric drives and *who makes it*, that metric
hasn't earned its place. Cut it or move it to Context.

## The session flow

### 1. Ground yourself before you grill
Read the actual data layer / code first. You can only run a sharp session if you
know what's *feasible* and what's *reachable*. Verify facts you can verify (does
this field exist? is outcome data joinable? is there an audit trail?) instead of
asking the user. In the By-RM rebuild, checking `lead.site.visit`, the `initiator`
field, and whether the conversation tracked assignment history each *changed the
design* — and each was a fact, not a preference. Don't ask what you can look up.

### 2. Tear down the existing thing, ruthlessly
Run every candidate metric through the bar below and name each failure out loud
with its consequence. Be specific: not "this is weak" but *"'Reply rate' is
labeled as RM diligence but it's actually the buyer's reply rate — a manager will
read it backwards."* See `references/metric-traps.md` for the full catalog. The
teardown earns trust and surfaces the real design problem.

### 3. Find the one question the thing should answer
A screen needs a spine: the single decision it exists to drive. ("Does
responsiveness convert?" "Who do I coach, on what?" "Where's the staffing gap?")
Everything that doesn't serve that spine is clutter or belongs on another screen.
Decide the **altitude** too — live-operational vs period-coaching vs strategic —
and refuse to duplicate a screen that already owns that altitude.

### 4. Grill the forks, one at a time, with worked examples
For each genuine decision, put it to the user as a fork (see "Forks" below). Where
a metric choice is subtle, **show what it does** with two contrasting personas
rather than asserting — this is the highest-leverage move in the whole method.
("Priya is fast on the first reply then ghosts; Arjun is slower but sustains every
chat. Score first-response-only and Priya ranks #1 — exactly backwards.") Then ask:
*what does each system make the leaderboard do?* A choice you can't illustrate with
a concrete divergence probably doesn't matter; a choice you can is worth the user's
call.

### 5. Lock each decision and move on
After a fork resolves, state the locked decision and the why in one line, then
build on it. Don't re-open settled ground. The running list of locked decisions is
the backbone of the eventual plan.

### 6. Reframe intractable problems instead of fighting them
When a denominator/attribution/ownership problem seems impossible, step back and
change the unit. The signature move from the By-RM session: *measure actions
historically (credit the actor who did the thing, at the moment they did it) and
measure state in real time (a current snapshot)* — which dissolved an "who owned
this lead historically" problem that had no answer. If you're stuck, you're
probably solving the wrong unit.

## The metric-quality bar

Run every proposed metric through these. The first one is the whole game.

- **Does it drive a decision, and whose?** No decision → vanity. Cut or demote.
- **Is it mostly within the actor's control?** This decides Score vs Context (next
  section). Lead quality, allocation, market, and other-channel effort are *not*
  the actor's control.
- **Is it labeled as what it actually measures?** Mislabels destroy trust on a
  performance screen. ("Reply rate" that's really *buyer* engagement.)
- **Is it gameable?** If people can hack the number without doing the real work
  (fire a reflexive "hi" to stop an SLA clock), it will train exactly that. Prefer
  un-gameable signals (did they *sustain* the conversation?).
- **Is it confounded?** If the number moves mostly because of things other than the
  thing you're trying to measure, it's measuring the confounder.
- **Does it survive only the survivors?** A metric computed only over successes
  (answered chats, closed deals) flatters everyone and hides the failures.
- **Is attribution stable over time?** If ownership/assignment changes, naive
  "current owner" attribution blames the wrong person for the past.

Full catalog with examples and fixes: `references/metric-traps.md`.

## Score vs Context — the core discipline

Split every metric into two buckets and treat them differently:

- **Scores** are *ranked* — they judge the actor and drive coaching/accountability.
  A metric earns Score status only if it's **mostly within the actor's control**.
- **Context** is *shown but never ranked* — it frames the situation so a Score is
  read fairly (lead-pool quality, current load, live backlog). Visually demote it
  (grey it, label it "context") so nobody mistakes it for a judgment.

Why this matters: scoring something the actor doesn't control (conversion driven by
lead quality, reply-rate driven by pool) punishes people for management's decisions
and breeds gaming or learned helplessness. Contextualizing it instead lets the
manager separate *bad situation* from *bad performer*. This split is usually the
single most important output of the session.

## Attribution: the traps that ruin "fair" metrics

These come up constantly and are subtle. Detailed treatment in
`references/metric-traps.md`; the headlines:

- **Single-channel outcome fallacy.** Don't credit/penalize one channel for a
  multi-causal outcome (don't judge WhatsApp work by deal conversion). Even *showing*
  the two columns side by side forces a false causal read — column adjacency implies
  causation no caveat can undo. Put the outcome where the *whole* effort is visible.
- **Point-in-time ownership.** To attribute history fairly when owners change, you
  need to know who owned it *at each moment*. If the data doesn't record that, either
  add a small append-only ledger (the honest investment) or be explicit that history
  before the ledger is best-effort. Never silently blame the current owner for the
  past.
- **Gameability vs the real job.** The easiest-to-measure proxy (first-response time)
  is often the easiest to game. Find the signal that tracks the actual job and
  resists theater.
- **Survivorship.** Make sure the *misses* are in the denominator, not just the hits.

## Forks: how to use AskUserQuestion well

Reserve forks for decisions that **change the architecture or the politics** and are
**genuinely the user's to make** — not things you can decide from sensible defaults
or verify in the code. For each fork:

- Frame 2–4 mutually exclusive options, each with its **tradeoff and consequence**,
  not just a label.
- Put your **recommendation first** and say why — you're a PM with a view, not a
  menu.
- Ask **one decisive fork at a time** and build the next on the answer. A session is
  a sequence of resolved forks, not a questionnaire dump.
- If the user pushes back on the framing itself (as they should), **update the
  framing** — a fork they reframe is the session working, not failing.

Good forks from the By-RM session: *unit of accountability* (owner vs actor),
*pull outcomes in now or build a hook*, *screen altitude*, *how to handle the
un-attributable misses*. Each changed what got built.

## Forward hooks, not false claims

When something is valuable but genuinely out of scope (or unfair to claim here),
don't fake it and don't drop it — **build the hook**. Keep stable keys/IDs and the
honest intermediate signals so the right screen can join against it later. In the
By-RM case: no conversion metric on the WhatsApp screen, but stable RM keys + a
clean engagement signal so a future multi-touch leads dashboard can do conversion
attribution *fairly*. You lose nothing; you just don't lie about causation now.

## Representation is half the work

A correct metric shown badly still fails the manager. Decide representation in the
same session:

- **Lead with the headline.** A summary strip / team number up top so the altitude-1
  read takes two seconds.
- **Encode visually.** good/warn/bad color, funnels, sparklines — so outliers pop
  without reading digits. Pair a visual with the exact number (a bar *and* its
  count) so people get proportion and precision at once.
- **Make it glanceable, then drillable.** Rank/sort by the headline Score; let the
  user drill to the rows behind a number so they can act, not just observe.
- **Explain how to read it, in place.** Managers don't share your model. Add help
  affordances (a "?" that opens *what this shows + how to read it*, with a visual
  legend for any color-coded widget) next to the thing it explains — on the column,
  not bolted onto the whole table. If a widget has colors or segments, the help
  should show a labeled sample, not just prose.

## Anti-patterns — stop and rethink if you catch these

- Adding a metric because it's *available*, not because it drives a decision.
- A metric whose value would be identical for a great and a terrible performer.
- Ranking people on a number driven mostly by their inputs (leads, territory).
- "We'll caveat it" — if the layout implies a false story, caveats won't save it.
- Cramming every metric onto one screen instead of choosing the spine.
- Asking the user something you could verify in the code in thirty seconds.
- Converging before the honesty problems are actually solved.

## When NOT to over-apply this

This is for measurement, analytics, performance, and decision-support surfaces —
where fairness and "does this drive action" are the crux. For a straightforward
CRUD form, a styling fix, or a feature with an obvious shape, a full grilling is
overkill; note the obvious choice and proceed. Use judgment: the heavier the
behavioral consequence of the thing, the more this method earns its time.
