"""Bottom-of-screen launcher. A prompt runs the chosen agent on that task; an empty prompt runs the eval
category. Start with `uv run --extra popup popup.py`."""

import json
import os
import shlex
import signal
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent
AGENTS = {"base": "base", "telemetry": "telemetry-only", "knowledge": "knowledge-only",
          "telemetry-knowledge": "telemetry-knowledge", "claude-code": "claude-code"}
CATEGORIES = {"all": None, "base": "sanity", "challenge": "challenge", "final": "final"}


def build_command(prompt, agent, category, desktop, privacy):
    """(shell command, env) for a run, or (None, reason) when it can't start."""
    preset = AGENTS[agent]
    env = {**os.environ, "SCREENSHOT_PRIVACY": "ocr" if privacy else "off", "DESKTOP_CONTROL": "1" if desktop else "0"}
    if prompt.strip():
        template = json.loads((ROOT / "evals/desktop/agents.json").read_text())[preset]
        if not desktop:  # templates set it inline, which beats the environment
            template = template.replace("DESKTOP_CONTROL=1", "DESKTOP_CONTROL=0")
        return template.replace("{instruction}", shlex.quote(prompt.strip())), env
    if not desktop:
        return None, "Eval needs desktop control"
    command = f"uv run python evals/desktop/run_desktop.py --agent {preset} --skip-description"
    if CATEGORIES[category]:
        command += f" --category {CATEGORIES[category]}"
    return command, env


def main():
    from AppKit import (NSApplication, NSApplicationActivationPolicyAccessory, NSBackingStoreBuffered, NSButton,
                        NSControlStateValueOn, NSFloatingWindowLevel, NSMakeRect, NSPanel, NSPopUpButton, NSScreen,
                        NSTextField, NSWindowStyleMaskClosable, NSWindowStyleMaskTitled, NSWindowStyleMaskUtilityWindow)
    from Foundation import NSObject, NSTimer
    from PyObjCTools import AppHelper

    class Controller(NSObject):
        def send_(self, sender):
            if self.proc or (sender == self.prompt and not self.prompt.stringValue().strip()):
                return  # an eval starts only from an explicit Send click
            command, env = build_command(self.prompt.stringValue(), self.agent.titleOfSelectedItem(),
                                         self.category.titleOfSelectedItem(), self.desktop.state() == NSControlStateValueOn,
                                         self.privacy.state() == NSControlStateValueOn)
            if command is None:
                self.status.setStringValue_(env)
                return
            print("$", command, flush=True)
            self.proc = subprocess.Popen(command, shell=True, env=env, cwd=ROOT)
            self.panel.orderOut_(None)  # keep the launcher out of the agent's screenshots and clicks
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(1.0, self, "poll:", None, True)

        def poll_(self, timer):
            if self.proc.poll() is None:
                return
            timer.invalidate()
            self.status.setStringValue_(f"Done: exit {self.proc.returncode}")
            self.proc = None
            self.panel.orderFrontRegardless()

        def tick_(self, timer):
            pass  # hands control back to Python so the Ctrl+C handler can run

        def windowWillClose_(self, notification):
            AppHelper.stopEventLoop()

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)  # no Dock icon
    width, height = 760, 84
    screen = NSScreen.mainScreen().visibleFrame()  # excludes the Dock, so the panel sits just above it
    panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(screen.origin.x + (screen.size.width - width) / 2, screen.origin.y + 12, width, height),
        NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskUtilityWindow, NSBackingStoreBuffered, False)
    panel.setTitle_("Telemetry AI")
    panel.setLevel_(NSFloatingWindowLevel)
    panel.setHidesOnDeactivate_(False)

    ctl = Controller.alloc().init()
    ctl.proc, ctl.panel = None, panel
    ctl.prompt = NSTextField.textFieldWithString_("")
    ctl.prompt.setPlaceholderString_("Task for the agent (leave empty to run the eval category)")
    ctl.prompt.setTarget_(ctl)
    ctl.prompt.setAction_("send:")  # Return sends
    ctl.prompt.cell().setSendsActionOnEndEditing_(False)  # not when focus moves (that fired a run at launch)
    send = NSButton.buttonWithTitle_target_action_("Send", ctl, "send:")
    ctl.desktop = NSButton.checkboxWithTitle_target_action_("Desktop control", None, None)
    ctl.desktop.setState_(NSControlStateValueOn)
    ctl.privacy = NSButton.checkboxWithTitle_target_action_("Privacy (OCR)", None, None)
    ctl.agent = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(0, 0, 0, 0), False)
    ctl.agent.addItemsWithTitles_(list(AGENTS))
    ctl.agent.selectItemWithTitle_("telemetry-knowledge")
    ctl.category = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(0, 0, 0, 0), False)
    ctl.category.addItemsWithTitles_(list(CATEGORIES))
    ctl.status = NSTextField.labelWithString_("")

    for view, frame in [(ctl.prompt, (12, 48, 640, 24)), (send, (660, 46, 88, 28)),
                        (ctl.desktop, (12, 14, 130, 22)), (ctl.privacy, (144, 14, 120, 22)),
                        (ctl.agent, (268, 12, 170, 26)), (ctl.category, (442, 12, 110, 26)),
                        (ctl.status, (560, 16, 190, 18))]:
        view.setFrame_(NSMakeRect(*frame))
        panel.contentView().addSubview_(view)
    panel.setDelegate_(ctl)
    panel.makeKeyAndOrderFront_(None)
    panel.makeFirstResponder_(ctl.prompt)
    app.activateIgnoringOtherApps_(True)
    # Ctrl+C quits cleanly; dying instantly made `uv run` report ESRCH looking up the vanished child
    signal.signal(signal.SIGINT, lambda *_: AppHelper.stopEventLoop())
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(0.2, ctl, "tick:", None, True)
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
