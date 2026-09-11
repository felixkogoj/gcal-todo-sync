#!/usr/bin/env python3
"""Add a task to a Microsoft To Do list on demand (e.g. from a chat request).

Usage:
    SYNC_SECRET_KEY=... python scripts/add_task.py --list "Aufgaben" --title "..." [--due YYYY-MM-DD]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import ms_graph  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", required=True, help="Exact list name, e.g. 'Aufgaben'")
    parser.add_argument("--title", required=True)
    parser.add_argument("--due", help="YYYY-MM-DD, optional")
    args = parser.parse_args()

    access_token = ms_graph.get_access_token()
    lists = ms_graph.list_lists(access_token)
    match = next((l for l in lists if l["displayName"].strip().lower() == args.list.strip().lower()), None)
    if not match:
        available = ", ".join(l["displayName"] for l in lists)
        print(f"Liste '{args.list}' nicht gefunden. Verfuegbare Listen: {available}")
        sys.exit(1)

    task = ms_graph.create_task(match["id"], args.title, args.due, access_token)
    due_note = f", faellig {args.due}" if args.due else ""
    print(f"Angelegt: '{task['title']}' in Liste '{match['displayName']}'{due_note}")


if __name__ == "__main__":
    main()
