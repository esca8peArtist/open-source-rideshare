# Inbox

> Drop tasks, ideas, or redirections here from your phone or any device.
> The orchestrator reads this at the start of every session and processes new items.
> After processing, items are moved to WORKLOG.md or PROJECTS.md and cleared from here.
>
> **Tip**: This file syncs via Obsidian if your vault is set up to include this directory.
> Add a task from your phone by editing this file in Obsidian.

---

## New Items
- [2026-04-17 02:18] I want to create a new menu in the stockbot project called Projected Returns and I want it to allow me to pick one of the models that I have created and have it graph the future predictions that it is making to influence its buy/sell decisions. My goal is to be able to pull up that graph for a stock that I own and see when a good time to sell would be based on the future projection
- [2026-04-17 02:14] 
<!-- Add tasks here. Format: - [date] [description] -->

<!-- Processed 2026-04-17 Session 248:
- [2026-04-17] mfg-farm: Build the ModRun cable management family in CadQuery. Parametric Python design: mounting rail (desk-edge clip mount, adhesive pad base, cable channel) + 3 clip variants for 3mm / 6mm / 12mm cable diameter. All parts parametric — dimensions as variables at top of script. Export STL files to projects/mfg-farm/stl/. Write a brief README in projects/mfg-farm/cadquery/ explaining how to adjust parameters and regenerate STLs. → Actioned: building CadQuery designs this session.
- [2026-04-17] stockbot: API is unreachable from Pi directly (Jetson firewall). Use SSH tunnel: ssh -f -N -L 18000:localhost:8000 xxsb-01 then hit http://localhost:18000 with STOCKBOT_API_KEY from env. Pull cycle logs and assess model performance across all 4 sessions. → Actioned: opening tunnel and pulling logs this session.
-->

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
