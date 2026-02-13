---
name: todo-list
description: Manage a simple ToDo list stored as a JSON file. Supports creating, listing, updating, and deleting tasks with status tracking (pending, in_progress, done). Use when the user wants to manage tasks, track to-dos, create a task list, or work with a JSON-based task tracker. Triggers on requests like "add a task", "show my todos", "mark task as done", "delete a task", or any todo/task management request.
---

# ToDo List Manager

Manage tasks in a local JSON file with full CRUD support. All output is structured JSON.

## Task Schema

```json
{
  "id": "8-char hex",
  "title": "Task title",
  "description": "Optional details",
  "status": "pending | in_progress | done",
  "created_at": "ISO 8601",
  "updated_at": "ISO 8601"
}
```

## Usage

Use `scripts/todo.py` for all operations. Default storage file is `./todos.json` in the current directory. Override with `--file PATH`.

### Add a task

```bash
python3 scripts/todo.py add --title "Buy groceries" --desc "Milk, eggs, bread" --status pending
```

`--desc` and `--status` are optional. Status defaults to `pending`.

### List tasks

```bash
python3 scripts/todo.py list                  # all tasks
python3 scripts/todo.py list --status done    # filter by status
```

### Update a task

```bash
python3 scripts/todo.py update --id abc12345 --status done
python3 scripts/todo.py update --id abc12345 --title "New title" --desc "New desc"
```

All fields except `--id` are optional; only provided fields are updated.

### Delete a task

```bash
python3 scripts/todo.py delete --id abc12345
```

## Workflow

1. Determine the user's intent (add / list / update / delete).
2. If adding, extract title, optional description, and optional status from the request.
3. If updating or deleting, run `list` first to find the task ID if the user refers to a task by name.
4. Run the appropriate command and present the JSON output to the user.
5. For batch operations, run multiple commands sequentially.
