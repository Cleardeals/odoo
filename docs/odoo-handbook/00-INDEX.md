# The Cleardeals Odoo Handbook

This is the single source of knowledge for working on the Cleardeals Odoo
system. It is written to take one specific person from "I have never opened
Odoo" to "I can ship a reviewed change to production", without needing anyone
to explain the basics to them in person.

## Who this is for

**You know Python, SQL and HTTP. You have never used Odoo.**

That is the assumption behind every page. The handbook does not teach you
Python, and it does not assume you have seen an ERP before. When it says
"a `Many2one`", it explains what that is; when it says "a dict comprehension",
it does not.

If you are an experienced Odoo developer joining this codebase, skip to
[Chapter 05](05-writing-a-module.md) and read forward — chapters 01–04 will be
mostly familiar, though §04's Odoo 19 changes are worth a skim because several
of them broke code that worked in earlier versions.

## The chapters

| # | Chapter | What you get out of it |
|---|---------|------------------------|
| 01 | [What Odoo is, and how this repo is laid out](01-what-is-odoo.md) | The mental model: what the framework does for you, and where every kind of file lives in this repository |
| 02 | [Getting started: your local environment](02-getting-started.md) | A running Odoo on your machine, developer mode on, and the handful of commands you will use every day |
| 03 | [The server process and execution modes](03-server-and-execution-modes.md) | What actually happens between `odoo-bin` and an HTTP response; threaded vs prefork; workers, crons and the watchdogs that kill them |
| 04 | [The ORM and how databases work in Odoo](04-orm-and-database.md) | The largest chapter. Models, fields, recordsets, transactions, constraints, and the performance traps |
| 05 | [Writing a custom module, end to end](05-writing-a-module.md) | Build one from an empty directory, using our conventions, and install it |
| 06 | [Views, actions and the web client](06-views-and-web-client.md) | XML views and inheritance, plus OWL components and our `cleardeals_ui` library |
| 07 | [Security: users, groups, ACLs, record rules](07-security.md) | Who can see what, and the `sudo()` discipline that keeps that true |
| 08 | [Controllers and HTTP](08-controllers-and-http.md) | Routes, JSON-RPC, webhooks, and the real endpoints we run |
| 09 | [Sessions and authentication](09-sessions.md) | Where a session physically lives, how it rotates, and why people get logged out |
| 10 | [The filestore, attachments and binary data](10-filestore-and-attachments.md) | Where uploaded files go, and why the database alone is not a backup |
| 11 | [Data files, external IDs, crons and configuration](11-data-files-and-crons.md) | Shipping data with a module, and scheduling work |
| 12 | [Migrations and upgrades](12-migrations.md) | Changing a schema that already has production data in it |
| 13 | [Testing](13-testing.md) | Our test framework, fixtures, runners, and what must be tested before merge |
| 14 | [Integrations: Pub/Sub, webhooks, WhatsApp](14-integrations.md) | How Odoo talks to the outside world here, and the one pattern you must not get wrong |
| 15 | [Coding conventions and the way we work](15-conventions.md) | The house style, the review skills, and the workflow from branch to merge |
| 16 | [Debugging, observability and operations](16-debugging-and-ops.md) | Reading logs, attaching a debugger, and a symptom→cause→fix table |
| 17 | [Cheat sheet, glossary and first-week exercises](17-cheatsheet-and-exercises.md) | The reference back-page, and three graded exercises to prove you have it |

## Three reading paths

**Day one — get productive (about half a day).**
Read [01](01-what-is-odoo.md) and [02](02-getting-started.md) end to end and get
the stack running. Then skim [04](04-orm-and-database.md) as far as "Recordsets"
and stop. Do not try to absorb the whole ORM chapter yet.

**First week — become dangerous.**
[04](04-orm-and-database.md) properly, then [05](05-writing-a-module.md),
[06](06-views-and-web-client.md), [07](07-security.md), and
[13](13-testing.md). Finish with the three exercises in
[17](17-cheatsheet-and-exercises.md). At that point you can pick up a real
ticket.

**Reference — when something specific bites you.**
[03](03-server-and-execution-modes.md), [08](08-controllers-and-http.md),
[09](09-sessions.md), [10](10-filestore-and-attachments.md),
[11](11-data-files-and-crons.md), [12](12-migrations.md) and
[16](16-debugging-and-ops.md) are written to be read out of order, when you need
them. The "where do I look for X" table in
[17](17-cheatsheet-and-exercises.md) maps symptoms to chapters.

## How this handbook relates to the skills

This repository carries a set of *skills* — structured instructions that an AI
coding assistant loads when it works on a particular kind of task. They live in
`.github/skills/` and `.claude/skills/`.

The distinction matters:

- **This handbook explains** how Odoo works and why we do things a certain way.
  It is for a human being, read once, and referred back to.
- **The skills enforce** those same conventions on a specific task, in the
  moment. They are procedures, not explanations.

Where they overlap, the skill is the operative version — it is what actually
runs during a review. The handbook tells you the reasoning behind it.
[Chapter 15](15-conventions.md) catalogues every skill with a one-line "invoke
this when…".

## Conventions used in these pages

**Odoo version.** Everything here is Odoo **19.0**, specifically the build this
repository vendors and runs (`19.0-20260528`). Odoo changes its internals
between major versions more freely than most frameworks. Where 19 differs from
what you will find in a blog post or an older StackOverflow answer, the text
says so explicitly, because those differences are the single most common source
of wasted time for someone new.

**Code snippets.** Almost every snippet is real code from this repository or
from the vendored Odoo source, and is attributed with a clickable path. When a
snippet is invented to illustrate a point rather than copied, it is labelled
*illustrative*.

**Source citations.** Claims about framework behaviour cite the file that
proves them, for example `odoo/http.py:945`. If you doubt a statement, open the
file — that is what the citation is for. The line numbers are correct for the
vendored source at the time of writing; treat them as a strong hint rather than
a guarantee if the source has since moved.

**Screenshots.** Taken from a real Odoo 19 instance running this repository's
modules, with seeded data. They live in [`images/`](images/).

**Callouts.**

> **Trap.** Something that will cost you an afternoon if you do not know it.

> **Our convention.** A Cleardeals decision, not an Odoo rule. Reasonable
> people could do it differently; we do it this way, consistently.

## Keeping it honest

A handbook that drifts from the code is worse than no handbook, because people
trust it. Two rules:

1. If you change something this document describes — a convention, a config
   key, a module boundary — update the chapter in the same pull request.
2. If you find something here that is wrong, fix it immediately rather than
   working around it. A wrong page has already misled someone.
