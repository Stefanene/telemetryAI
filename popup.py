"""Desktop overlay with a prompt and visible agent response. Start with
`uv run --extra popup popup.py`, or add --demo for an offline synthetic response."""

import argparse
import json
import re
import sys
import tempfile
import time
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



def response_text(stdout, stderr="", returncode=0, *, evaluation=False):
    """Extract the final answer from CLI output, without displaying progress JSON/logs."""
    clean = lambda text: re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text).strip()
    stdout, stderr = clean(stdout), clean(stderr)
    final = None
    for line in reversed(stdout.splitlines()):
        try:
            candidate = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(candidate, dict) and "result" in candidate:
            final = candidate
            break
    if returncode:
        detail = stderr[-2000:] or (str(final["result"]) if final else stdout[-2000:])
        return f"Agent exited with code {returncode}.\n\n{detail or 'No error details were returned.'}"
    if final is not None:
        result = final["result"]
        if isinstance(result, str):
            try:
                structured = json.loads(result)
            except ValueError:
                structured = None
            if isinstance(structured, dict):
                result = structured
        if isinstance(result, dict):
            summary = result.get("summary") or result.get("agent_summary") or result.get("reason")
            text = str(summary) if summary else json.dumps(result, ensure_ascii=False, indent=2)
            if result.get("status"):
                text += f"\n\nVerification: {result['status']}"
            if result.get("reason") and result["reason"] != summary:
                text += f"\n{result['reason']}"
        else:
            text = str(result) if result is not None else "No answer was returned."
        if final.get("is_error"):
            text = "Agent reported an error.\n\n" + text
        return text[:12000]
    if evaluation:
        return "Evaluation process finished. Review its reported grades below.\n\n" + (stdout[-10000:] or "No results were returned.")
    return (stdout[-12000:] or "The process finished without an answer.")


class BackgroundRun:
    """File-backed output avoids pipe-buffer deadlocks; the UI only polls completion."""
    def __init__(self, command, env, *, evaluation=False):
        self.stdout = tempfile.TemporaryFile()
        self.stderr = tempfile.TemporaryFile()
        self.evaluation = evaluation
        self.returncode = None
        try:
            self.proc = subprocess.Popen(command, shell=isinstance(command, str), env=env, cwd=ROOT,
                                         stdout=self.stdout, stderr=self.stderr, start_new_session=True)
        except Exception:
            self.stdout.close()
            self.stderr.close()
            raise

    @staticmethod
    def tail(stream):
        stream.seek(0, os.SEEK_END)
        stream.seek(max(0, stream.tell() - 65536))
        return stream.read().decode("utf-8", errors="replace")

    def poll(self):
        code = self.proc.poll()
        if code is None:
            return None
        self.returncode = code
        try:
            return response_text(self.tail(self.stdout), self.tail(self.stderr), code, evaluation=self.evaluation)
        finally:
            self.stdout.close()
            self.stderr.close()

    def cancel(self):
        if self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
                self.proc.wait(timeout=2)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.proc.wait()
        self.stdout.close()
        self.stderr.close()


def demo_command(prompt):
    return [sys.executable, str(Path(__file__).resolve()), "--demo-worker", prompt]


def main(*, demo=False, demo_screenshot=None):
    from AppKit import (NSApplication, NSApplicationActivationPolicyAccessory, NSBackingStoreBuffered, NSButton,
                        NSControlStateValueOn, NSFloatingWindowLevel, NSMakeRect, NSPanel, NSPopUpButton, NSScreen,
                        NSTextField, NSWindowStyleMaskClosable, NSWindowStyleMaskTitled, NSWindowStyleMaskUtilityWindow,
                        NSScrollView, NSTextView, NSFont, NSColor, NSMakeSize,
                        NSViewWidthSizable, NSViewHeightSizable, NSBitmapImageFileTypePNG,
                        NSAppearance, NSAppearanceNameAqua, NSView, NSRectFill)
    from Foundation import NSObject, NSTimer
    from PyObjCTools import AppHelper

    class Surface(NSView):
        def drawRect_(self, rect):
            NSColor.windowBackgroundColor().setFill()
            NSRectFill(rect)

    class Controller(NSObject):
        def showReply_(self, text):
            self.reply.setString_(text)
            self.reply.scrollRangeToVisible_((0, 0))

        def send_(self, sender):
            prompt = self.prompt.stringValue().strip()
            if self.run or (sender == self.prompt and not prompt):
                return
            if demo:
                command, env = demo_command(prompt or "Demonstrate the evaluation response"), dict(os.environ)
            else:
                command, env = build_command(prompt, self.agent.titleOfSelectedItem(),
                                             self.category.titleOfSelectedItem(), self.desktop.state() == NSControlStateValueOn,
                                             self.privacy.state() == NSControlStateValueOn)
            if command is None:
                self.status.setStringValue_(env)
                self.showReply_(env)
                return
            self.submitted = prompt or f"Run {self.category.titleOfSelectedItem()} evaluations"
            self.showReply_(f"YOU\n{self.submitted}\n\nTELEMETRY AI\nWorking on your request…")
            try:
                self.run = BackgroundRun(command, env, evaluation=not prompt and not demo)
            except OSError as exc:
                self.status.setStringValue_("Could not start")
                self.showReply_(f"Could not start the agent: {exc}")
                return
            self.send.setEnabled_(False)
            self.status.setStringValue_("Demo running…" if demo else "Running…")
            if not demo:
                self.panel.orderOut_(None)  # keep overlay out of agent screenshots and clicks
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(0.2, self, "poll:", None, True)

        def poll_(self, timer):
            if self.run is None:
                timer.invalidate()
                return
            response = self.run.poll()
            if response is None:
                return
            timer.invalidate()
            code = self.run.returncode
            self.run = None
            self.showReply_(f"YOU\n{self.submitted}\n\nTELEMETRY AI{' · OFFLINE DEMO' if demo else ''}\n{response}")
            self.status.setStringValue_(("Demo complete · no API" if demo else "Response ready") if code == 0 else f"Failed · exit {code}")
            self.send.setEnabled_(True)
            self.panel.orderFrontRegardless()
            if demo_screenshot:
                NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(0.3, self, "captureDemo:", None, False)

        def startDemo_(self, timer):
            self.prompt.setStringValue_("Can you show your answer here in the overlay?")
            self.send_(self.send)

        def captureDemo_(self, timer):
            # Render the real AppKit view after the asynchronous demo response is displayed.
            view = self.panel.contentView()
            view.displayIfNeeded()
            bitmap = view.bitmapImageRepForCachingDisplayInRect_(view.bounds())
            view.cacheDisplayInRect_toBitmapImageRep_(view.bounds(), bitmap)
            data = bitmap.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
            if not data.writeToFile_atomically_(str(demo_screenshot), True):
                raise RuntimeError("Could not save the demo screenshot")
            print(json.dumps({"demo_screenshot": str(demo_screenshot), "response": str(self.reply.string())}), flush=True)
            AppHelper.stopEventLoop()

        def tick_(self, timer):
            pass

        def windowWillClose_(self, notification):
            AppHelper.stopEventLoop()

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    width, height = 820, 360
    screen = NSScreen.mainScreen().visibleFrame()
    panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(screen.origin.x + (screen.size.width - width) / 2, screen.origin.y + 12, width, height),
        NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskUtilityWindow, NSBackingStoreBuffered, False)
    panel.setAppearance_(NSAppearance.appearanceNamed_(NSAppearanceNameAqua))
    panel.setContentView_(Surface.alloc().initWithFrame_(NSMakeRect(0, 0, width, height)))
    panel.setTitle_("Telemetry AI · Offline demo" if demo else "Telemetry AI")
    panel.setLevel_(NSFloatingWindowLevel)
    panel.setHidesOnDeactivate_(False)

    ctl = Controller.alloc().init()
    ctl.run, ctl.panel = None, panel
    ctl.prompt = NSTextField.textFieldWithString_("")
    ctl.prompt.setPlaceholderString_("Try a prompt — synthetic response, no API calls" if demo else "Task for the agent (leave empty to run the eval category)")
    ctl.prompt.setTarget_(ctl)
    ctl.prompt.setAction_("send:")
    ctl.prompt.cell().setSendsActionOnEndEditing_(False)
    ctl.send = NSButton.buttonWithTitle_target_action_("Send", ctl, "send:")
    ctl.desktop = NSButton.checkboxWithTitle_target_action_("Desktop control", None, None)
    ctl.desktop.setState_(NSControlStateValueOn)
    ctl.privacy = NSButton.checkboxWithTitle_target_action_("Privacy (OCR)", None, None)
    ctl.agent = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(0, 0, 0, 0), False)
    ctl.agent.addItemsWithTitles_(list(AGENTS))
    ctl.agent.selectItemWithTitle_("telemetry-knowledge")
    ctl.category = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(0, 0, 0, 0), False)
    ctl.category.addItemsWithTitles_(list(CATEGORIES))
    ctl.status = NSTextField.labelWithString_("Offline demo · no API" if demo else "Ready")
    ctl.status.setFont_(NSFont.systemFontOfSize_(11))
    ctl.status.setTextColor_(NSColor.secondaryLabelColor())
    heading = NSTextField.labelWithString_("Conversation")
    heading.setFont_(NSFont.boldSystemFontOfSize_(14))
    scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(12, 96, 796, 222))
    scroll.setHasVerticalScroller_(True)
    scroll.setBorderType_(1)
    ctl.reply = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 776, 222))
    ctl.reply.setEditable_(False)
    ctl.reply.setSelectable_(True)
    ctl.reply.setRichText_(False)
    ctl.reply.setFont_(NSFont.systemFontOfSize_(14))
    ctl.reply.setTextColor_(NSColor.labelColor())
    ctl.reply.setBackgroundColor_(NSColor.textBackgroundColor())
    ctl.reply.setTextContainerInset_(NSMakeSize(14, 12))
    ctl.reply.setVerticallyResizable_(True)
    ctl.reply.setHorizontallyResizable_(False)
    ctl.reply.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
    ctl.reply.textContainer().setWidthTracksTextView_(True)
    scroll.setDocumentView_(ctl.reply)
    ctl.showReply_("Ask a question or give the agent a task. Its answer will appear here.\n\n" +
                   ("Offline demo is enabled: no model calls or desktop actions will run." if demo else
                    "The overlay hides during agent execution and returns with the response. Text can be selected and copied."))

    for view, frame in [(heading, (16, 327, 300, 22)), (scroll, (12, 96, 796, 222)),
                        (ctl.prompt, (12, 48, 700, 24)), (ctl.send, (720, 46, 88, 28)),
                        (ctl.desktop, (12, 14, 130, 22)), (ctl.privacy, (144, 14, 120, 22)),
                        (ctl.agent, (268, 12, 170, 26)), (ctl.category, (442, 12, 110, 26)),
                        (ctl.status, (560, 16, 248, 18))]:
        view.setFrame_(NSMakeRect(*frame))
        panel.contentView().addSubview_(view)
    if demo:
        for control in (ctl.desktop, ctl.privacy, ctl.agent, ctl.category):
            control.setEnabled_(False)
    panel.setDelegate_(ctl)
    panel.makeKeyAndOrderFront_(None)
    panel.makeFirstResponder_(ctl.prompt)
    app.activateIgnoringOtherApps_(True)
    signal.signal(signal.SIGINT, lambda *_: AppHelper.stopEventLoop())
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(0.2, ctl, "tick:", None, True)
    if demo_screenshot:
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(0.3, ctl, "startDemo:", None, False)
    try:
        AppHelper.runEventLoop()
    finally:
        if ctl.run:
            ctl.run.cancel()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Offline synthetic responses; no model or desktop calls")
    parser.add_argument("--demo-worker", help=argparse.SUPPRESS)
    parser.add_argument("--demo-screenshot", type=Path, help="With --demo, exercise Send, save the rendered panel, and exit")
    args = parser.parse_args()
    if args.demo_screenshot and not args.demo:
        parser.error("--demo-screenshot requires --demo")
    if args.demo_worker is not None:
        time.sleep(0.3)
        print(json.dumps({"result": "The overlay received your request and displayed this response successfully.\n\n"
                          "This is a synthetic agent response. No API key was used, and no desktop task was executed."}))
    else:
        main(demo=args.demo, demo_screenshot=args.demo_screenshot)
