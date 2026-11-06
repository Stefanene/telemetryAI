"""Read-only macOS telemetry collectors that inform agent decisions and grade eval runs.

Placeholders: every function is a TODO. Hook points are marked `TODO(telemetry)` in desktop.py,
agent.py and evals/desktop/run_desktop.py.

Rules for implementations: collectors only read (never click, type or change settings), and must
not return secrets. Window titles, logs and UI labels can contain them, so redact before returning.
"""

from __future__ import annotations

from pathlib import Path


def frontmost_app() -> dict:
    """The app in front: {"name", "bundle_id", "pid"}.

    TODO: `osascript -e 'tell application "System Events" to get {name, bundle identifier, unix id}
    of first process whose frontmost is true'` (or NSWorkspace via JXA, like desktop.points_per_pixel).
    """
    raise NotImplementedError


def window_list() -> list[dict]:
    """Visible windows: [{"app", "title", "bounds": [x, y, w, h]}].

    TODO: JXA over System Events processes/windows, or CGWindowListCopyWindowInfo via ObjC bridge.
    """
    raise NotImplementedError


def ui_tree(app: str | None = None, depth: int = 3) -> dict:
    """Accessibility tree of the front window of `app` (default: frontmost): nested
    {"role", "label", "value", "position", "size", "children"}, cut off at `depth`.

    TODO: System Events `UI elements` walk (needs Accessibility permission, same as desktop actions).
    Lets the operator target elements by label instead of guessing pixels from a screenshot.
    """
    raise NotImplementedError


def system_snapshot() -> dict:
    """{"cpu_percent", "memory": {...}, "battery": {...}, "disk_free_gb", "top_processes": [...]}.

    TODO: `ps -Ao pid,pcpu,pmem,comm -r`, `vm_stat`, `pmset -g batt`, `df -g /`.
    """
    raise NotImplementedError


def recent_logs(minutes: int = 5, predicate: str | None = None) -> list[str]:
    """Unified log lines from the last `minutes`, optionally filtered by a `log` predicate.

    TODO: `log show --last {minutes}m --style compact [--predicate ...]`, capped in size.
    """
    raise NotImplementedError


def file_events(root: Path, since: float) -> list[dict]:
    """Files under `root` created/modified/deleted since the epoch time `since`:
    [{"path", "event", "mtime", "size"}].

    TODO: stat walk compared to a snapshot taken at `since` (stdlib; FSEvents only if needed).
    Used by the eval to record what an agent touched in the sandbox beyond what graders check.
    """
    raise NotImplementedError


def snapshot() -> dict:
    """One combined record ({"time", "frontmost_app", "windows", "system"}) for per-action and per-run telemetry.

    TODO: call the collectors above; a collector that fails should become {"error": ...}, not raise.
    """
    raise NotImplementedError


#: TODO(telemetry): wrap the read-only collectors (frontmost_app, window_list, ui_tree, system_snapshot)
#: as @function_tool and add them to the chat agent in agent.py.
TELEMETRY_TOOLS: list = []
