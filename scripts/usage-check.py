#!/usr/bin/env python3
"""
usage-check.py — Weekly session usage tracker for the SuperClaude orchestrator.

Parses WORKLOG.md to count orchestrator sessions per week and reports
usage against the configured budget. Used by:
  - The orchestrator at the start of each session (throttle check)
  - The user at any time for a quick usage overview

Output modes:
  python usage-check.py            → human-readable report
  python usage-check.py --json     → JSON for scripting
  python usage-check.py --check    → exit 0 if under budget, exit 1 if over
  python usage-check.py --checkin  → compact one-liner for CHECKIN.md
"""

import re
import sys
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from collections import defaultdict

# ── Config ────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
WORKLOG = REPO_ROOT / "WORKLOG.md"
PROJECTS = REPO_ROOT / "PROJECTS.md"

# Week runs Monday–Sunday (ISO week).
# These should match the values in PROJECTS.md ## Usage Budget section.
DEFAULT_WEEKLY_BUDGET = 20
DEFAULT_DAILY_BUDGET = 5
WARN_PCT = 0.75  # warn at 75% of budget


def parse_budget_from_projects() -> tuple[int, int]:
    """Read weekly and daily budget from PROJECTS.md if present."""
    weekly = DEFAULT_WEEKLY_BUDGET
    daily = DEFAULT_DAILY_BUDGET
    if not PROJECTS.exists():
        return weekly, daily
    text = PROJECTS.read_text()
    m = re.search(r"weekly[_\s]session[_\s]budget\s*[:=]\s*(\d+)", text, re.IGNORECASE)
    if m:
        weekly = int(m.group(1))
    m = re.search(r"daily[_\s]session[_\s]budget\s*[:=]\s*(\d+)", text, re.IGNORECASE)
    if m:
        daily = int(m.group(1))
    return weekly, daily


def parse_sessions(worklog_path: Path) -> list[date]:
    """
    Extract one date per session from WORKLOG.md.
    Lines matching '## YYYY-MM-DD' are session headers.
    Returns list of dates (one per session entry, oldest first).
    """
    if not worklog_path.exists():
        return []
    dates: list[date] = []
    pattern = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})")
    for line in worklog_path.read_text().splitlines():
        m = pattern.match(line)
        if m:
            try:
                dates.append(datetime.strptime(m.group(1), "%Y-%m-%d").date())
            except ValueError:
                pass
    return sorted(dates)


def iso_week_key(d: date) -> str:
    """Return 'YYYY-Www' ISO week key for a date."""
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def week_range(d: date) -> tuple[date, date]:
    """Return (monday, sunday) for the ISO week containing d."""
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def build_report() -> dict:
    weekly_budget, daily_budget = parse_budget_from_projects()
    session_dates = parse_sessions(WORKLOG)

    today = date.today()
    current_week = iso_week_key(today)
    current_monday, current_sunday = week_range(today)

    # Group by ISO week
    by_week: dict[str, list[date]] = defaultdict(list)
    for d in session_dates:
        by_week[iso_week_key(d)].append(d)

    # By day for daily budget check
    by_day: dict[date, int] = defaultdict(int)
    for d in session_dates:
        by_day[d] += 1

    # Current week stats
    this_week_sessions = by_week.get(current_week, [])
    this_week_count = len(this_week_sessions)
    today_count = by_day.get(today, 0)

    # Rolling 7 days
    rolling_start = today - timedelta(days=6)
    rolling_count = sum(1 for d in session_dates if d >= rolling_start)

    # Last 4 weeks for trend
    weeks = []
    for offset in range(3, -1, -1):
        ref = today - timedelta(weeks=offset)
        wk = iso_week_key(ref)
        mon, sun = week_range(ref)
        count = len(by_week.get(wk, []))
        weeks.append({
            "week": wk,
            "start": str(mon),
            "end": str(sun),
            "sessions": count,
            "is_current": wk == current_week,
        })

    # Budget status
    week_pct = this_week_count / weekly_budget if weekly_budget else 0
    day_pct = today_count / daily_budget if daily_budget else 0
    over_week = this_week_count >= weekly_budget
    over_day = today_count >= daily_budget
    warn_week = week_pct >= WARN_PCT and not over_week
    warn_day = day_pct >= WARN_PCT and not over_day

    return {
        "today": str(today),
        "current_week": current_week,
        "week_start": str(current_monday),
        "week_end": str(current_sunday),
        "budgets": {
            "weekly": weekly_budget,
            "daily": daily_budget,
        },
        "usage": {
            "this_week": this_week_count,
            "today": today_count,
            "rolling_7d": rolling_count,
            "total_all_time": len(session_dates),
        },
        "status": {
            "over_weekly_budget": over_week,
            "warn_weekly_budget": warn_week,
            "over_daily_budget": over_day,
            "warn_daily_budget": warn_day,
            "week_pct": round(week_pct * 100, 1),
            "day_pct": round(day_pct * 100, 1),
        },
        "weekly_trend": weeks,
        "recommendation": _recommend(over_week, warn_week, over_day, warn_day,
                                      this_week_count, weekly_budget,
                                      today_count, daily_budget),
    }


def _recommend(over_w, warn_w, over_d, warn_d, wk_used, wk_budget, d_used, d_budget) -> str:
    if over_w:
        return (f"OVER weekly budget ({wk_used}/{wk_budget}). "
                "Orchestrator should idle until next Monday or user raises limit.")
    if over_d:
        return (f"OVER daily budget ({d_used}/{d_budget}). "
                "Orchestrator should idle until tomorrow.")
    if warn_w:
        remaining = wk_budget - wk_used
        return (f"Approaching weekly budget — {remaining} sessions remaining this week. "
                "Prioritise high-value tasks only.")
    if warn_d:
        remaining = d_budget - d_used
        return f"Approaching daily budget — {remaining} sessions remaining today."
    return "Usage nominal. No throttling needed."


def print_report(r: dict) -> None:
    w = r["status"]
    u = r["usage"]
    b = r["budgets"]

    week_bar = _bar(u["this_week"], b["weekly"])
    day_bar = _bar(u["today"], b["daily"])

    status_w = "OVER" if w["over_weekly_budget"] else ("WARN" if w["warn_weekly_budget"] else "OK  ")
    status_d = "OVER" if w["over_daily_budget"] else ("WARN" if w["warn_daily_budget"] else "OK  ")

    print(f"\n{'='*55}")
    print(f"  SuperClaude Usage Check — {r['today']}")
    print(f"{'='*55}")
    print(f"  Week ({r['current_week']}, {r['week_start']} → {r['week_end']})")
    print(f"  [{status_w}] {week_bar}  {u['this_week']:>2}/{b['weekly']} sessions  ({w['week_pct']}%)")
    print(f"  Today")
    print(f"  [{status_d}] {day_bar}  {u['today']:>2}/{b['daily']} sessions  ({w['day_pct']}%)")
    print(f"  Rolling 7d: {u['rolling_7d']} sessions  |  All-time: {u['total_all_time']}")
    print()
    print("  Weekly trend:")
    for wk in r["weekly_trend"]:
        marker = " ◀ current" if wk["is_current"] else ""
        bar = _bar(wk["sessions"], b["weekly"], width=20)
        print(f"    {wk['week']}  {bar}  {wk['sessions']:>2}/{b['weekly']}{marker}")
    print()
    print(f"  ➜  {r['recommendation']}")
    print(f"{'='*55}\n")
    print("  To check manually: claude.ai → Settings → Usage & billing")
    print()


def _bar(used: int, total: int, width: int = 24) -> str:
    if total == 0:
        return "░" * width
    filled = min(int(used / total * width), width)
    color = "█" if used < total * WARN_PCT else ("▓" if used < total else "░")
    return "█" * filled + "░" * (width - filled)


def checkin_line(r: dict) -> str:
    u = r["usage"]
    b = r["budgets"]
    s = r["status"]
    flag = "🔴" if s["over_weekly_budget"] else ("🟡" if s["warn_weekly_budget"] else "🟢")
    return (f"{flag} Usage this week: {u['this_week']}/{b['weekly']} sessions "
            f"({s['week_pct']}%) | today: {u['today']}/{b['daily']} | "
            f"rolling 7d: {u['rolling_7d']} | check: claude.ai → Settings → Usage & billing")


if __name__ == "__main__":
    args = sys.argv[1:]
    report = build_report()

    if "--json" in args:
        print(json.dumps(report, indent=2))
    elif "--check" in args:
        # Exit 1 if over any budget (for use in orchestrator scripts)
        s = report["status"]
        if s["over_weekly_budget"] or s["over_daily_budget"]:
            print(f"BUDGET EXCEEDED: {report['recommendation']}")
            sys.exit(1)
        print(f"OK: {report['recommendation']}")
        sys.exit(0)
    elif "--checkin" in args:
        print(checkin_line(report))
    else:
        print_report(report)
