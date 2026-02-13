#!/usr/bin/env python3
"""Simple ToDo List manager with JSON storage.

Usage:
    python3 todo.py <command> [options]

Commands:
    add      --title TITLE [--desc DESC] [--status STATUS] [--file FILE]
    list     [--status STATUS] [--file FILE]
    update   --id ID [--title TITLE] [--desc DESC] [--status STATUS] [--file FILE]
    delete   --id ID [--file FILE]

Status values: pending (default), in_progress, done
Default file: ./todos.json
"""

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone


def load(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save(path, todos):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(todos, f, ensure_ascii=False, indent=2)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cmd_add(args):
    todos = load(args.file)
    task = {
        "id": uuid.uuid4().hex[:8],
        "title": args.title,
        "description": args.desc or "",
        "status": args.status,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    todos.append(task)
    save(args.file, todos)
    print(json.dumps({"action": "added", "task": task}, ensure_ascii=False, indent=2))


def cmd_list(args):
    todos = load(args.file)
    if args.status:
        todos = [t for t in todos if t["status"] == args.status]
    result = {
        "total": len(todos),
        "tasks": todos,
    }
    if args.status:
        result["filter"] = {"status": args.status}
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_update(args):
    todos = load(args.file)
    for t in todos:
        if t["id"] == args.id:
            if args.title:
                t["title"] = args.title
            if args.desc is not None:
                t["description"] = args.desc
            if args.status:
                t["status"] = args.status
            t["updated_at"] = now_iso()
            save(args.file, todos)
            print(json.dumps({"action": "updated", "task": t}, ensure_ascii=False, indent=2))
            return
    print(json.dumps({"error": f"Task '{args.id}' not found"}), file=sys.stderr)
    sys.exit(1)


def cmd_delete(args):
    todos = load(args.file)
    original_len = len(todos)
    todos = [t for t in todos if t["id"] != args.id]
    if len(todos) == original_len:
        print(json.dumps({"error": f"Task '{args.id}' not found"}), file=sys.stderr)
        sys.exit(1)
    save(args.file, todos)
    print(json.dumps({"action": "deleted", "id": args.id}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="ToDo List Manager")
    sub = parser.add_subparsers(dest="command", required=True)

    # add
    p_add = sub.add_parser("add")
    p_add.add_argument("--title", required=True)
    p_add.add_argument("--desc", default="")
    p_add.add_argument("--status", default="pending", choices=["pending", "in_progress", "done"])
    p_add.add_argument("--file", default="./todos.json")

    # list
    p_list = sub.add_parser("list")
    p_list.add_argument("--status", choices=["pending", "in_progress", "done"])
    p_list.add_argument("--file", default="./todos.json")

    # update
    p_upd = sub.add_parser("update")
    p_upd.add_argument("--id", required=True)
    p_upd.add_argument("--title")
    p_upd.add_argument("--desc")
    p_upd.add_argument("--status", choices=["pending", "in_progress", "done"])
    p_upd.add_argument("--file", default="./todos.json")

    # delete
    p_del = sub.add_parser("delete")
    p_del.add_argument("--id", required=True)
    p_del.add_argument("--file", default="./todos.json")

    args = parser.parse_args()
    {"add": cmd_add, "list": cmd_list, "update": cmd_update, "delete": cmd_delete}[args.command](args)


if __name__ == "__main__":
    main()
