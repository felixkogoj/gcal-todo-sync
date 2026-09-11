#!/usr/bin/env python3
"""Read-only helper: prints every list and its open tasks.

Run locally (needs SYNC_SECRET_KEY set in the environment):
    SYNC_SECRET_KEY=... python scripts/list_tasks.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import ms_graph  # noqa: E402


def main():
    access_token = ms_graph.get_access_token()
    for lst in ms_graph.list_lists(access_token):
        print(f"\n=== {lst['displayName']} ===")
        tasks = ms_graph.list_tasks(lst["id"], access_token)
        if not tasks:
            print("  (leer)")
            continue
        for task in tasks:
            if task.get("status") == "completed":
                continue
            due = task.get("dueDateTime", {}).get("dateTime", "")[:10]
            due_str = f" (fällig {due})" if due else ""
            print(f"  - {task['title']}{due_str}")


if __name__ == "__main__":
    main()
