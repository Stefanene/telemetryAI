"""Launcher command building (no AppKit, nothing launched)."""

from popup import build_command


def test_build_command_picks_agent_task_or_eval_run():
    cmd, env = build_command("Open Calculator", "telemetry-knowledge", "all", desktop=True, privacy=True)
    assert "KNOWLEDGE_GRAPH_ENABLED=1" in cmd and cmd.endswith("agent.py 'Open Calculator'")
    assert env["SCREENSHOT_PRIVACY"] == "ocr" and env["DESKTOP_CONTROL"] == "1"

    cmd, env = build_command("Open Calculator", "base", "all", desktop=False, privacy=False)
    assert "DESKTOP_CONTROL=0" in cmd and "DESKTOP_CONTROL=1" not in cmd and env["SCREENSHOT_PRIVACY"] == "off"

    cmd, _ = build_command("", "telemetry", "all", desktop=True, privacy=False)
    assert cmd.endswith("--agent telemetry-only --skip-description")
    cmd, _ = build_command("  ", "claude-code", "base", desktop=True, privacy=False)
    assert cmd.endswith("--agent claude-code --skip-description --category sanity")

    assert build_command("", "base", "final", desktop=False, privacy=False) == (None, "Eval needs desktop control")
