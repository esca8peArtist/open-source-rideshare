# Inbox

> Drop tasks, ideas, or redirections here from your phone or any device.
> The orchestrator reads this at the start of every session and processes new items.
> After processing, items are moved to WORKLOG.md or PROJECTS.md and cleared from here.
>
> **Tip**: This file syncs via Obsidian if your vault is set up to include this directory.
> Add a task from your phone by editing this file in Obsidian.

---

## New Items
<!-- Add tasks here. Format: - [date] [description] -->

<!-- Processed 2026-04-18 Session 362:
- [2026-04-18] stockbot Ensemble Return Stacker — COMPLETE. All deliverables confirmed:
  ensemble_stacker.py, 4 API endpoints, projected returns regressor fix, 10+ AAPL stackers
  trained in models/ensemble_stackers/, frontend UI wired in ModelBuilderPage. DEPLOY_READY
  created to trigger Jetson deploy. PROJECTS.md stockbot focus updated.
-->

<!-- Processed 2026-04-18 Session 316:
- [2026-04-17] stockbot Projected Returns page — ALREADY DONE (commit 76a4142, Session prior to 316). Full frontend (ProjectedReturnsPage.tsx) + backend endpoint (/api/models/{id}/projected-returns) + sidebar routing all confirmed. No work needed. Confirmed stockbot is #1 priority. Next: Paper Trading Dashboard page (monitoring live sessions, equity curve, cycle log).
-->

<!-- Processed 2026-04-14 Session 106:
- [15:56] Discord bot showing same status info → investigated and answered in CHECKIN.md
-->

<!-- Processed 2026-04-13 Session 99:
- [17:39] Jetson/paper trading status → answered in CHECKIN.md
- [17:38] Python 3.12 install → answered in CHECKIN.md (no longer needed; stockbot running on 3.11)
-->

---

## Processing Rules

The orchestrator will:
1. Read all items in "New Items"
2. For project tasks: add to PROJECTS.md current focus for the relevant project
3. For research requests: action immediately or add to Exploration Queue in PROJECTS.md
4. For redirections/priority changes: update PROJECTS.md priority order
5. For questions: answer in CHECKIN.md and await next check-in
6. Clear this section after processing and log what was done in WORKLOG.md
