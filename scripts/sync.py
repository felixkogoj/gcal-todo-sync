#!/usr/bin/env python3
"""Two-way sync driver between Microsoft To Do and Google Calendar.

This script owns the Microsoft To Do side directly (via Graph API) and the
diff/matching logic. It has no Google credentials, so any mutation on the
Google Calendar side is handed back to the calling agent as a "pending
action" that it must execute with the Google Calendar connector tools.

Commands:
  window                          Print the sync date window (no auth needed).
  sync --events-file PATH         Do the full diff. Applies all Microsoft-side
                                   changes directly. Prints JSON with
                                   "pendingGoogleActions" the agent must run.
  finalize --results-file PATH    Record the outcome of the pending Google
                                   actions (new event ids for creates) and
                                   finish updating state.json.

State persists in state.json (plain, no secrets) and secrets/ms_token.enc
(encrypted refresh token) - both committed back to the repo by the agent
after each run.
"""
import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
import ms_graph  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
STATE_FILE = os.path.join(ROOT, "state.json")

WINDOW_PAST_DAYS = 3
WINDOW_FUTURE_DAYS = 60

MARKER_PREFIX = "<!--gcalsync:list="
MARKER_RE_LIST = "list="
MARKER_RE_TASK = ";task="


def make_marker(list_id, task_id):
    return f"<!--gcalsync:list={list_id};task={task_id}-->"


def parse_marker(description):
    if not description or MARKER_PREFIX not in description:
        return None
    try:
        tail = description.split(MARKER_PREFIX, 1)[1]
        tail = tail.split("-->", 1)[0]
        list_id, task_id = tail.split(";task=")
        return list_id, task_id
    except Exception:
        return None


def strip_marker(description):
    if not description or MARKER_PREFIX not in description:
        return description or ""
    head = description.split(MARKER_PREFIX, 1)[0]
    return head.rstrip()


def content_hash(*parts):
    h = hashlib.sha1()
    for p in parts:
        h.update((p or "").encode("utf-8"))
        h.update(b"|")
    return h.hexdigest()


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"pairs": [], "pendingActions": []}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write("\n")


def window_bounds():
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=WINDOW_PAST_DAYS)
    end = today + timedelta(days=WINDOW_FUTURE_DAYS)
    return start.isoformat(), end.isoformat()


def cmd_window(_args):
    start, end = window_bounds()
    print(json.dumps({"windowStart": start, "windowEnd": end}, indent=2))


def task_due_date(task):
    due = task.get("dueDateTime")
    if not due or not due.get("dateTime"):
        return None
    return due["dateTime"][:10]


def cmd_sync(args):
    with open(args.events_file, "r", encoding="utf-8") as f:
        events = json.load(f)
    events_by_id = {e["id"]: e for e in events}

    access_token = ms_graph.get_access_token()
    lists = ms_graph.list_lists(access_token)
    tasks_by_id = {}
    for lst in lists:
        for task in ms_graph.list_tasks(lst["id"], access_token):
            task["_listId"] = lst["id"]
            tasks_by_id[task["id"]] = task

    state = load_state()
    pairs = {(p["taskId"]): p for p in state["pairs"]}
    win_start, win_end = window_bounds()

    pending_actions = []

    def add_pending(action_type, payload):
        action_id = uuid.uuid4().hex[:12]
        pending_actions.append({"actionId": action_id, "type": action_type, **payload})
        return action_id

    handled_task_ids = set()
    handled_event_ids = set()

    # 1. Walk existing linked pairs: detect deletions/completions/updates.
    for task_id, pair in list(pairs.items()):
        handled_task_ids.add(task_id)
        handled_event_ids.add(pair["eventId"])
        task = tasks_by_id.get(task_id)
        event = events_by_id.get(pair["eventId"])
        task_gone = task is None or task.get("status") == "completed"

        if task_gone:
            if event is not None:
                add_pending("delete_event", {"eventId": pair["eventId"], "reason": "task done or deleted"})
            del pairs[task_id]
            continue

        if event is None:
            # Only treat as a real deletion if the event's last known date
            # was inside the window we just queried - otherwise it's simply
            # out of range this run, not necessarily gone.
            if win_start <= pair.get("eventDate", win_start) <= win_end:
                ms_graph.delete_task(task["_listId"], task_id, access_token)
                del pairs[task_id]
            continue

        new_task_hash = content_hash(task["title"], task_due_date(task) or "")
        new_event_hash = content_hash(event.get("summary", ""), event.get("startDate", ""))

        task_changed = new_task_hash != pair.get("taskHash")
        event_changed = new_event_hash != pair.get("eventHash")

        if task_changed and not event_changed:
            add_pending(
                "update_event",
                {
                    "eventId": pair["eventId"],
                    "summary": task["title"],
                    "startDate": task_due_date(task),
                    "reason": "task changed",
                },
            )
        elif event_changed and not task_changed:
            ms_graph.update_task(
                task["_listId"], task_id, access_token,
                title=event.get("summary"), due_date=event.get("startDate"),
            )

        pair["taskHash"] = new_task_hash if not task_changed else pair.get("taskHash")
        pair["eventHash"] = new_event_hash if not event_changed else pair.get("eventHash")
        pair["eventDate"] = event.get("startDate", pair.get("eventDate"))
        pairs[task_id] = pair

    # 2. Unlinked Microsoft tasks with a due date in window -> need a new event.
    for task_id, task in tasks_by_id.items():
        if task_id in handled_task_ids or task.get("status") == "completed":
            continue
        if ms_graph.linked_event_id(task):
            continue  # linked from a previous run but pair.json is stale; skip safely
        due = task_due_date(task)
        if not due or not (win_start <= due <= win_end):
            continue
        add_pending(
            "create_event",
            {
                "taskId": task_id,
                "listId": task["_listId"],
                "summary": task["title"],
                "startDate": due,
                "description": make_marker(task["_listId"], task_id),
            },
        )

    # 3. Unlinked Google events in window -> create a Microsoft task directly.
    for event_id, event in events_by_id.items():
        if event_id in handled_event_ids:
            continue
        marker = parse_marker(event.get("description", ""))
        if marker:
            continue  # already linked, pair.json just hasn't caught up
        start_date = event.get("startDate")
        if not start_date or not (win_start <= start_date <= win_end):
            continue
        # Use the first available list for new events created from Google.
        target_list = lists[0]["id"] if lists else None
        if not target_list:
            continue
        new_task = ms_graph.create_task(
            target_list, event.get("summary", "(ohne Titel)"), start_date, access_token,
            linked_event_id_value=event_id,
        )
        pairs[new_task["id"]] = {
            "taskId": new_task["id"],
            "listId": target_list,
            "eventId": event_id,
            "taskHash": content_hash(new_task["title"], start_date),
            "eventHash": content_hash(event.get("summary", ""), start_date),
            "eventDate": start_date,
        }
        new_description = (strip_marker(event.get("description", "")) + "\n\n" + make_marker(target_list, new_task["id"])).strip()
        add_pending(
            "update_event",
            {"eventId": event_id, "description": new_description, "reason": "stamp link after task creation"},
        )

    state["pairs"] = list(pairs.values())
    state["pendingActions"] = pending_actions
    save_state(state)

    print(json.dumps({"pendingGoogleActions": pending_actions}, indent=2, ensure_ascii=False))


def cmd_finalize(args):
    with open(args.results_file, "r", encoding="utf-8") as f:
        results = json.load(f)
    results_by_id = {r["actionId"]: r for r in results}

    state = load_state()
    pending = {a["actionId"]: a for a in state.get("pendingActions", [])}
    pairs = {p["taskId"]: p for p in state["pairs"]}

    access_token = None
    for action_id, action in pending.items():
        result = results_by_id.get(action_id)
        if not result or result.get("status") != "done":
            continue
        if action["type"] == "create_event":
            new_event_id = result["googleEventId"]
            if access_token is None:
                access_token = ms_graph.get_access_token()
            ms_graph.add_linked_resource(
                action["listId"], action["taskId"], new_event_id, access_token,
            )
            pairs[action["taskId"]] = {
                "taskId": action["taskId"],
                "listId": action["listId"],
                "eventId": new_event_id,
                "taskHash": content_hash(action["summary"], action["startDate"]),
                "eventHash": content_hash(action["summary"], action["startDate"]),
                "eventDate": action["startDate"],
            }
        # update_event / delete_event: state.json was already updated in cmd_sync.

    state["pairs"] = list(pairs.values())
    state["pendingActions"] = []
    save_state(state)
    print(json.dumps({"ok": True, "pairs": len(state["pairs"])}, indent=2))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("window")

    sync_p = sub.add_parser("sync")
    sync_p.add_argument("--events-file", required=True)

    finalize_p = sub.add_parser("finalize")
    finalize_p.add_argument("--results-file", required=True)

    args = parser.parse_args()
    {"window": cmd_window, "sync": cmd_sync, "finalize": cmd_finalize}[args.command](args)


if __name__ == "__main__":
    main()
