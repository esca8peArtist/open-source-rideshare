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

<!-- Processed 2026-04-14 Session 120:
- [21:36] Discord notifications too frequent — user wants only the ~2-hour periodic ones, not per-session → noted in WORKLOG, feedback saved, orchestrator will limit Discord pings to once per ~2hr window going forward
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
