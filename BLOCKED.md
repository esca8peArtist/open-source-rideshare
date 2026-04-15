# Blocked Items

> Items the orchestrator cannot proceed on without user input.
> The orchestrator checks this at the start of each session.
> When you've unblocked something, add a note in the "Resolution" field — the orchestrator will pick it up and clear the entry.

---

## Format

```
### [Project] — [Short description of block]
**Date blocked**: YYYY-MM-DD
**Context**: What was being attempted and why it's blocked
**What I need**: Specific question or decision needed from user
**Resolution**: [Leave blank — user fills this in]
```

---

## Active Blocks

## Resolved (Archive)

### open-source-rideshare — GitHub push blocked: no HTTPS credentials or SSH key
**Date blocked**: 2026-04-12
**Date resolved**: 2026-04-14
**Resolution**: SSH key (`id_ed25519`) confirmed present on Pi and remote URL already set to SSH (`git@github.com:SuperClaude-Org/SuperClaude_Framework.git`). Push should work.

### stockbot — Python 3.12 required but not available on Pi
**Date blocked**: 2026-04-12
**Date resolved**: 2026-04-12
**Resolution**: Option C chosen. pandas-ta replaced with `ta` library across technical_indicators.py and dashboard_api.py. requirements.txt updated. Venv needs manual rebuild by user (see CHECKIN.md). Orchestrator can proceed once venv is rebuilt.

### All projects — Git identity not configured on Pi
**Date blocked**: 2026-04-12
**Date resolved**: 2026-04-12
**Resolution**: git identity confirmed as name=thorn, email=thorn@local. Orchestrator can proceed with commits.
