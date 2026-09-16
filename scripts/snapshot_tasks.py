#!/usr/bin/env python3
"""Write a full snapshot of all open Microsoft To Do tasks (every list, with
and without a due date) to tasks_snapshot.json at the repo root.

This exists because the calendar sync (sync.py) deliberately skips tasks
that have no due date and live in a non-weekday list (no sensible calendar
date to give them) - see README "Bekannte Einschraenkungen". Those tasks
never reach Google Calendar, so an agent that only reads the calendar never
sees them either. This script is the second, calendar-independent channel:
it dumps every open task as-is, so an agent can read tasks_snapshot.json
directly (via `git clone`/`git pull` of this repo) any time it needs
Felix's current to-do state, regardless of whether a task has a date.

Run as part of the hourly sync routine (in addition to, not instead of,
sync.py): needs SYNC_SECRET_KEY set in the environment, same as the other
scripts.
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
import ms_graph  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
SNAPSHOT_FILE = os.path.join(ROOT, "tasks_snapshot.json")


def task_due_date(task):
    due = task.get("dueDateTime")
    if not due or not due.get("dateTime"):
        return None
    return due["dateTime"][:10]


def main():
    access_token = ms_graph.get_access_token()
    lists = ms_graph.list_lists(access_token)

    snapshot = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "lists": {},
    }

    for lst in lists:
        name = lst.get("displayName", lst["id"])
        open_tasks = []
        for task in ms_graph.list_tasks(lst["id"], access_token):
            if task.get("status") == "completed":
                continue
            open_tasks.append({
                "id": task["id"],
                "title": task.get("title", ""),
                "due": task_due_date(task),
                "hasCalendarEvent": ms_graph.linked_event_id(task) is not None,
            })
        snapshot["lists"][name] = open_tasks

    with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)
        f.write("\n")

    total = sum(len(v) for v in snapshot["lists"].values())
    print(json.dumps({"ok": True, "lists": len(snapshot["lists"]), "openTasks": total}, indent=2))


if __name__ == "__main__":
    main()
