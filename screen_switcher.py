#!/usr/bin/env python3
"""
Screen Layout Switcher — macOS menu bar app.

Switches your HDMI external display between two arrangements ("above"
and "right" of the MacBook), with per-layout fine-tune offsets, a
configurable global hotkey, and start-at-login via launchd.

Modes:
  python3 screen_switcher.py                 # menu bar app (default)
  python3 screen_switcher.py --config        # open settings window
  python3 screen_switcher.py --toggle        # toggle layout once and exit
  python3 screen_switcher.py --install-agent
  python3 screen_switcher.py --uninstall-agent

Requires:
  - displayplacer  (brew install jakehilborn/jakehilborn/displayplacer)
  - python-tk@3.14 (brew install python-tk@3.14)
  - rumps, pynput  (pip install -r requirements.txt — see setup.sh)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


# ===== paths & constants =================================================

APP_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = Path.home() / ".screen_switcher.json"

LAUNCH_AGENT_LABEL = "com.vincentrost.screenswitcher"
LAUNCH_AGENT_PATH = (
    Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"
)
LOG_PATH = APP_DIR / "screen_switcher.log"

EXTERNAL_ID = "DD110D51-7707-4A87-98E1-AEAA88626864"
MACBOOK_ID = "37D8832A-2D66-02CA-B9F7-8F30A301B230"

EXTERNAL_BASE = (
    f"id:{EXTERNAL_ID} res:1920x1080 hz:60 color_depth:8 "
    "enabled:true scaling:off origin:(0,0) degree:0"
)

DEFAULTS: dict = {
    "above_macbook_x": 278,
    "right_macbook_y": 124,
    "hotkey": "<cmd>+<alt>+<ctrl>+r",
}

ABOVE_X_RANGE = (-500, 1000)
RIGHT_Y_RANGE = (-300, 500)


# ===== settings ==========================================================

def load_settings() -> dict:
    s = DEFAULTS.copy()
    try:
        with open(SETTINGS_PATH) as f:
            data = json.load(f)
        for key, default in DEFAULTS.items():
            v = data.get(key)
            if isinstance(v, type(default)):
                s[key] = v
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return s


def save_settings(s: dict) -> None:
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_PATH, "w") as f:
            json.dump(s, f, indent=2)
    except OSError:
        pass


# ===== layouts & displayplacer ==========================================

def make_layouts(settings: dict) -> dict:
    return {
        "above": {
            "title": "Above",
            "subtitle": "External screen sits above the MacBook",
            "fine_tune": {
                "label": "Horizontal alignment",
                "value_label": "MacBook x-offset",
                "settings_key": "above_macbook_x",
                "range": ABOVE_X_RANGE,
                "left_hint": "MacBook left",
                "right_hint": "MacBook right",
            },
            "args": [
                EXTERNAL_BASE,
                f"id:{MACBOOK_ID} res:1470x956 hz:60 color_depth:8 "
                f"enabled:true scaling:on "
                f"origin:({settings['above_macbook_x']},1080) degree:0",
            ],
        },
        "right": {
            "title": "Right",
            "subtitle": "External screen sits to the right of the MacBook",
            "fine_tune": {
                "label": "Vertical alignment",
                "value_label": "MacBook y-offset",
                "settings_key": "right_macbook_y",
                "range": RIGHT_Y_RANGE,
                "left_hint": "MacBook higher",
                "right_hint": "MacBook lower",
            },
            "args": [
                EXTERNAL_BASE,
                f"id:{MACBOOK_ID} res:1470x956 hz:60 color_depth:8 "
                f"enabled:true scaling:on "
                f"origin:(-1470,{settings['right_macbook_y']}) degree:0",
            ],
        },
    }


def apply_layout(settings: dict, name: str) -> tuple[bool, str]:
    layouts = make_layouts(settings)
    if name not in layouts:
        return False, f"Unknown layout: {name}"
    try:
        result = subprocess.run(
            ["displayplacer", *layouts[name]["args"]],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        return False, (
            "displayplacer not found.\n"
            "Install: brew install jakehilborn/jakehilborn/displayplacer"
        )
    except subprocess.TimeoutExpired:
        return False, "displayplacer timed out."
    if result.returncode != 0:
        return False, result.stderr.strip() or result.stdout.strip()
    return True, "OK"


def detect_state() -> tuple[str | None, int | None, int | None]:
    """Return (layout_name, mb_x, mb_y).

    layout_name is "above", "right", "custom" or None on error.
    """
    try:
        out = subprocess.run(
            ["displayplacer", "list"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout
    except Exception:
        return None, None, None

    in_mb = False
    for line in out.splitlines():
        if MACBOOK_ID in line:
            in_mb = True
            continue
        if in_mb and line.startswith("Origin:"):
            m = re.search(r"\((-?\d+),(-?\d+)\)", line)
            if not m:
                return None, None, None
            x, y = int(m.group(1)), int(m.group(2))
            if y >= 1000:
                return "above", x, y
            if x <= -1000:
                return "right", x, y
            return "custom", x, y
    return None, None, None


# ===== hotkey utilities ==================================================

MOD_DISPLAY = {
    "<cmd>": "\u2318",     # ⌘
    "<alt>": "\u2325",     # ⌥
    "<ctrl>": "\u2303",    # ⌃
    "<shift>": "\u21e7",   # ⇧
}

MOD_ORDER = ["ctrl", "alt", "shift", "cmd"]


def pretty_hotkey(hk: str) -> str:
    if not hk:
        return ""
    out = []
    for part in hk.split("+"):
        part = part.strip()
        if part in MOD_DISPLAY:
            out.append(MOD_DISPLAY[part])
        elif part.startswith("<") and part.endswith(">"):
            out.append(part[1:-1].upper())
        else:
            out.append(part.upper())
    return "".join(out)


# ===== launch agent ======================================================

def venv_python() -> str:
    """Path to a Python that has all deps installed."""
    venv_py = APP_DIR / ".venv" / "bin" / "python"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def launch_agent_plist() -> str:
    py = venv_python()
    script = APP_DIR / "screen_switcher.py"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCH_AGENT_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{py}</string>
        <string>{script}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>ProcessType</key>
    <string>Interactive</string>
    <key>LimitLoadToSessionType</key>
    <string>Aqua</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>StandardOutPath</key>
    <string>{LOG_PATH}</string>
    <key>StandardErrorPath</key>
    <string>{LOG_PATH}</string>
</dict>
</plist>
"""


def launchctl_target() -> str:
    """`gui/<uid>/<label>` — the modern launchctl target syntax."""
    import os
    return f"gui/{os.getuid()}/{LAUNCH_AGENT_LABEL}"


def launch_agent_runtime_state() -> dict:
    """Return runtime info from `launchctl print` (PID, last exit code, etc.)."""
    if not launch_agent_installed():
        return {"loaded": False}
    try:
        result = subprocess.run(
            ["launchctl", "print", launchctl_target()],
            capture_output=True, text=True, timeout=5,
        )
    except Exception as e:
        return {"loaded": False, "error": str(e)}
    if result.returncode != 0:
        return {"loaded": False, "error": result.stderr.strip()}

    info: dict = {"loaded": True}
    for raw in result.stdout.splitlines():
        line = raw.strip()
        for key in ("pid", "state", "last exit code", "runs"):
            prefix = f"{key} ="
            if line.startswith(prefix):
                info[key.replace(" ", "_")] = line[len(prefix):].strip()
    return info


def restart_launch_agent() -> tuple[bool, str]:
    if not launch_agent_installed():
        return False, "Launch agent not installed (run --install-agent)."
    try:
        result = subprocess.run(
            ["launchctl", "kickstart", "-k", launchctl_target()],
            capture_output=True, text=True, timeout=5,
        )
    except Exception as e:
        return False, str(e)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()
    return True, "kicked"


def print_status() -> None:
    s = load_settings()
    layout, mb_x, mb_y = detect_state()

    def hdr(text: str) -> None:
        print(f"\n\033[1m{text}\033[0m")

    hdr("Settings")
    print(f"  file: {SETTINGS_PATH}")
    print(f"  above_macbook_x: {s['above_macbook_x']}")
    print(f"  right_macbook_y: {s['right_macbook_y']}")
    print(f"  hotkey:          {s['hotkey'] or '(not set)'}  "
          f"({pretty_hotkey(s['hotkey']) or 'n/a'})")

    hdr("Display")
    if layout in ("above", "right"):
        print(f"  layout: {layout}")
        print(f"  MacBook origin: ({mb_x}, {mb_y})")
    elif layout == "custom":
        print(f"  layout: custom (MacBook origin {mb_x}, {mb_y})")
    else:
        print("  could not read displays (is displayplacer installed?)")

    hdr("Permissions")
    print(f"  Accessibility trust: "
          f"{'granted' if is_trusted() else 'NOT granted (hotkey will not fire)'}")
    print(f"  Python binary:       {python_binary()}")

    hdr("Launch agent")
    state = launch_agent_runtime_state()
    print(f"  installed: {launch_agent_installed()}")
    print(f"  plist:     {LAUNCH_AGENT_PATH}")
    print(f"  loaded:    {state.get('loaded', False)}")
    for key in ("pid", "state", "last_exit_code", "runs"):
        if key in state:
            print(f"  {key.replace('_', ' '):<10} {state[key]}")
    if "error" in state:
        print(f"  error: {state['error']}")

    hdr("Log")
    print(f"  file: {LOG_PATH}")
    if LOG_PATH.exists():
        try:
            with open(LOG_PATH) as f:
                lines = f.readlines()
        except OSError as e:
            print(f"  could not read: {e}")
        else:
            print(f"  size: {LOG_PATH.stat().st_size} bytes "
                  f"({len(lines)} lines)")
            tail = lines[-10:] if len(lines) > 10 else lines
            print("  last 10 lines:")
            for line in tail:
                print(f"    | {line.rstrip()}")
    else:
        print("  (no log yet)")
    print()


def launch_agent_installed() -> bool:
    return LAUNCH_AGENT_PATH.exists()


# ===== macOS permissions =================================================

def python_binary() -> Path:
    """Resolve the Python binary path that pynput's listener runs as.

    This is the path macOS attributes Accessibility / Input Monitoring
    permission to.
    """
    return Path(sys.executable).resolve()


def is_trusted() -> bool:
    """True if the running process has the Accessibility permission."""
    try:
        from ApplicationServices import AXIsProcessTrusted
        return bool(AXIsProcessTrusted())
    except Exception:
        return False


def request_trust(prompt: bool = True) -> bool:
    """Trigger the macOS Accessibility prompt for this process."""
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions
        opts = {"AXTrustedCheckOptionPrompt": prompt}
        return bool(AXIsProcessTrustedWithOptions(opts))
    except Exception:
        return False


def open_accessibility_settings() -> None:
    subprocess.Popen([
        "open",
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    ])


def open_input_monitoring_settings() -> None:
    subprocess.Popen([
        "open",
        "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
    ])


def reveal_python_in_finder() -> None:
    subprocess.Popen(["open", "-R", str(python_binary())])


def install_launch_agent() -> tuple[bool, str]:
    try:
        LAUNCH_AGENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        LAUNCH_AGENT_PATH.write_text(launch_agent_plist())
        subprocess.run(
            ["launchctl", "unload", str(LAUNCH_AGENT_PATH)],
            capture_output=True,
        )
        result = subprocess.run(
            ["launchctl", "load", "-w", str(LAUNCH_AGENT_PATH)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False, (result.stderr or result.stdout).strip()
        return True, str(LAUNCH_AGENT_PATH)
    except OSError as e:
        return False, str(e)


def uninstall_launch_agent() -> tuple[bool, str]:
    try:
        if LAUNCH_AGENT_PATH.exists():
            subprocess.run(
                ["launchctl", "unload", str(LAUNCH_AGENT_PATH)],
                capture_output=True,
            )
            LAUNCH_AGENT_PATH.unlink()
        return True, ""
    except OSError as e:
        return False, str(e)


# ===== menu bar app ======================================================

def run_menu_bar_app() -> None:
    try:
        import rumps
    except ImportError:
        sys.exit("rumps not installed. Run: ./setup.sh")
    try:
        from pynput import keyboard
    except ImportError:
        sys.exit("pynput not installed. Run: ./setup.sh")

    LAYOUT_GLYPH = {"above": "\u25b2", "right": "\u25b6"}  # ▲ ▶

    class MenuApp(rumps.App):
        def __init__(self) -> None:
            self.settings = load_settings()
            current, _, _ = detect_state()
            self.current = current if current in ("above", "right") else "above"

            super().__init__(
                "ScreenSwitcher",
                title=LAYOUT_GLYPH.get(self.current, "?"),
                quit_button=None,
            )

            self.above_item = rumps.MenuItem(
                "Above", callback=lambda _: self._enqueue(self._set_layout, "above")
            )
            self.right_item = rumps.MenuItem(
                "Right", callback=lambda _: self._enqueue(self._set_layout, "right")
            )
            self.toggle_item = rumps.MenuItem(
                "Toggle", callback=lambda _: self._enqueue(self._toggle)
            )
            self.hotkey_item = rumps.MenuItem("Hotkey: …")
            self.hotkey_item.set_callback(None)
            self.settings_item = rumps.MenuItem(
                "Settings\u2026", callback=lambda _: self._open_settings()
            )
            self.quit_item = rumps.MenuItem(
                "Quit", callback=lambda _: self._quit()
            )

            self.menu = [
                self.above_item,
                self.right_item,
                None,
                self.toggle_item,
                self.hotkey_item,
                None,
                self.settings_item,
                None,
                self.quit_item,
            ]

            self._pending: list = []
            self.hotkey_listener: keyboard.GlobalHotKeys | None = None

            self._refresh_menu()
            self._last_settings_mtime = self._mtime()

            if is_trusted():
                self._restart_hotkey_listener()
            else:
                rumps.notification(
                    "Screen Switcher",
                    "Accessibility permission required",
                    "Hotkey is disabled until Python is granted Accessibility "
                    "and Input Monitoring permission.",
                )
                request_trust(prompt=True)

            rumps.Timer(self._tick_pending, 0.1).start()
            rumps.Timer(self._tick_poll, 2.0).start()
            rumps.Timer(self._tick_trust, 5.0).start()

        # -- helpers ---------------------------------------------------

        def _mtime(self) -> float:
            try:
                return SETTINGS_PATH.stat().st_mtime
            except OSError:
                return 0.0

        def _enqueue(self, fn, *args) -> None:
            """Schedule fn(*args) to run on the main thread."""
            self._pending.append((fn, args))

        def _tick_pending(self, _timer) -> None:
            while self._pending:
                fn, args = self._pending.pop(0)
                try:
                    fn(*args)
                except Exception as e:
                    print(f"action failed: {e}", file=sys.stderr)

        def _tick_poll(self, _timer) -> None:
            mt = self._mtime()
            if mt > self._last_settings_mtime:
                self._last_settings_mtime = mt
                self.settings = load_settings()
                self._refresh_menu()
                self._restart_hotkey_listener()

            current, _, _ = detect_state()
            if current in ("above", "right") and current != self.current:
                self.current = current
                self._refresh_menu()

        def _tick_trust(self, _timer) -> None:
            """If the user just granted Accessibility, start the listener."""
            if self.hotkey_listener is None and is_trusted():
                self._restart_hotkey_listener()
                rumps.notification(
                    "Screen Switcher",
                    "Hotkey active",
                    f"Toggle with {pretty_hotkey(self.settings.get('hotkey', ''))}",
                )

        def _refresh_menu(self) -> None:
            self.title = LAYOUT_GLYPH.get(self.current, "?")
            self.above_item.state = 1 if self.current == "above" else 0
            self.right_item.state = 1 if self.current == "right" else 0
            hk = self.settings.get("hotkey", "")
            pretty = pretty_hotkey(hk)
            self.hotkey_item.title = (
                f"Hotkey: {pretty}" if pretty else "Hotkey: (not set)"
            )
            self.toggle_item.title = f"Toggle  {pretty}" if pretty else "Toggle"

        # -- actions ---------------------------------------------------

        def _set_layout(self, name: str) -> None:
            ok, msg = apply_layout(self.settings, name)
            if ok:
                self.current = name
                self._refresh_menu()
            else:
                rumps.notification(
                    "Screen Switcher", "Failed to apply layout", msg
                )

        def _toggle(self) -> None:
            self._set_layout("right" if self.current == "above" else "above")

        def _open_settings(self) -> None:
            subprocess.Popen(
                [venv_python(), str(APP_DIR / "screen_switcher.py"), "--config"]
            )

        def _quit(self) -> None:
            if self.hotkey_listener:
                try:
                    self.hotkey_listener.stop()
                except Exception:
                    pass
            rumps.quit_application()

        # -- hotkey ----------------------------------------------------

        def _restart_hotkey_listener(self) -> None:
            if self.hotkey_listener:
                try:
                    self.hotkey_listener.stop()
                except Exception:
                    pass
                self.hotkey_listener = None

            hk = self.settings.get("hotkey")
            if not hk:
                return

            try:
                listener = keyboard.GlobalHotKeys(
                    {hk: lambda: self._enqueue(self._toggle)}
                )
                listener.daemon = True
                listener.start()
                self.hotkey_listener = listener
            except Exception as e:
                print(f"failed to bind hotkey {hk!r}: {e}", file=sys.stderr)

    MenuApp().run()


# ===== settings window ===================================================

def run_config_window() -> None:
    try:
        import tkinter as tk
        from tkinter import ttk, messagebox
    except ImportError:
        sys.exit("tkinter not available. brew install python-tk@3.14")

    # Tk keysyms for modifier keys (mapped to pynput hotkey names).
    HELD_MOD_KEYSYMS = {
        "Control_L": "ctrl", "Control_R": "ctrl",
        "Shift_L": "shift", "Shift_R": "shift",
        "Alt_L": "alt", "Alt_R": "alt",
        "Option_L": "alt", "Option_R": "alt",
        "Meta_L": "cmd", "Meta_R": "cmd",
        "Command_L": "cmd", "Command_R": "cmd",
        "Super_L": "cmd", "Super_R": "cmd",
    }

    # Multi-character Tk keysyms that map to pynput Key enum names.
    # (Tk uses X11 legacy keysyms: "Prior" = page up, "Next" = page down.)
    SPECIAL_KEYSYMS = {
        "Escape": "esc",
        "Return": "enter",
        "BackSpace": "backspace",
        "Tab": "tab",
        "space": "space",
        "Delete": "delete",
        "Insert": "insert",
        "Up": "up", "Down": "down", "Left": "left", "Right": "right",
        "Home": "home", "End": "end",
        "Prior": "page_up", "Next": "page_down",
        "Page_Up": "page_up", "Page_Down": "page_down",
        "Caps_Lock": "caps_lock",
        "Num_Lock": "num_lock",
        "Scroll_Lock": "scroll_lock",
        "Pause": "pause",
        "Print": "print_screen",
        "Menu": "menu",
        **{f"F{i}": f"f{i}" for i in range(1, 21)},
    }

    NUMPAD_CHARS = {
        "KP_Add": "+", "KP_Subtract": "-", "KP_Multiply": "*",
        "KP_Divide": "/", "KP_Decimal": ".", "KP_Equal": "=",
    }

    def keysym_to_token(keysym: str) -> str | None:
        """Translate a Tk keysym to a pynput hotkey token, or None if unsupported."""
        if keysym in SPECIAL_KEYSYMS:
            return f"<{SPECIAL_KEYSYMS[keysym]}>"

        # Numpad keys → equivalent regular key
        if keysym.startswith("KP_"):
            rest = keysym[3:]
            if rest.isdigit():
                return rest
            if keysym in NUMPAD_CHARS:
                return NUMPAD_CHARS[keysym]
            if rest == "Enter":
                return "<enter>"
            if rest == "Space":
                return "space"
            return None

        if len(keysym) == 1:
            return keysym.lower()

        # Unknown / unsupported keysym
        return None

    def validate_hotkey(hk: str) -> tuple[bool, str]:
        """Return (ok, error_message) by attempting to parse with pynput."""
        try:
            from pynput.keyboard import HotKey
            HotKey.parse(hk)
            return True, ""
        except Exception as e:
            return False, str(e)

    class App(tk.Tk):
        PAD = 18

        def __init__(self) -> None:
            super().__init__()
            self.title("Screen Switcher \u2014 Settings")
            self.geometry("520x640")
            self.resizable(False, False)

            self.settings = load_settings()
            layout, mb_x, mb_y = detect_state()
            if layout == "above" and mb_x is not None:
                self.settings["above_macbook_x"] = mb_x
            elif layout == "right" and mb_y is not None:
                self.settings["right_macbook_y"] = mb_y
            save_settings(self.settings)

            self.current = tk.StringVar(
                value=layout if layout in ("above", "right") else "above"
            )
            self.slider_var = tk.DoubleVar()

            self.recording = False
            self._held_mods: list[str] = []

            self._build_ui()
            self._on_layout_change(apply=False)
            self.protocol("WM_DELETE_WINDOW", self._on_close)
            self.bind_all("<KeyPress>", self._on_keypress)
            self.bind_all("<KeyRelease>", self._on_keyrelease)

        def _build_ui(self) -> None:
            style = ttk.Style(self)
            try:
                style.theme_use("aqua")
            except tk.TclError:
                pass
            style.configure("Title.TLabel", font=("SF Pro Display", 16, "bold"))
            style.configure("Sub.TLabel", font=("SF Pro Text", 11), foreground="#666")
            style.configure("Section.TLabel", font=("SF Pro Text", 12, "bold"))
            style.configure("Hint.TLabel", font=("SF Pro Text", 10), foreground="#888")
            style.configure("Status.TLabel", font=("SF Mono", 10), foreground="#444")
            style.configure("HotKey.TLabel", font=("SF Mono", 13, "bold"))

            outer = ttk.Frame(self, padding=self.PAD)
            outer.pack(fill="both", expand=True)

            ttk.Label(outer, text="Screen Layout", style="Title.TLabel").pack(anchor="w")
            ttk.Label(
                outer,
                text="Toggle between the two saved arrangements.",
                style="Sub.TLabel",
            ).pack(anchor="w", pady=(2, 12))

            seg = ttk.Frame(outer)
            seg.pack(fill="x")
            for name in ("above", "right"):
                ttk.Radiobutton(
                    seg,
                    text=name.capitalize(),
                    value=name,
                    variable=self.current,
                    command=lambda: self._on_layout_change(apply=True),
                ).pack(side="left", padx=(0, 16))

            self.subtitle = ttk.Label(outer, text="", style="Sub.TLabel")
            self.subtitle.pack(anchor="w", pady=(8, 0))

            ttk.Separator(outer, orient="horizontal").pack(fill="x", pady=(14, 0))

            ft = ttk.Frame(outer, padding=(0, 14))
            ft.pack(fill="x")

            self.ft_label = ttk.Label(ft, text="", style="Section.TLabel")
            self.ft_label.pack(anchor="w")
            ttk.Label(
                ft,
                text="Drag and release to apply. Saved automatically.",
                style="Sub.TLabel",
            ).pack(anchor="w", pady=(2, 8))

            self.ft_value = ttk.Label(ft, text="", style="Sub.TLabel")
            self.ft_value.pack(anchor="w")

            self.slider = ttk.Scale(
                ft,
                variable=self.slider_var,
                command=self._on_slider_drag,
                orient="horizontal",
                length=460,
            )
            self.slider.pack(fill="x", pady=(2, 2))
            self.slider.bind("<ButtonRelease-1>", self._on_slider_release)

            hints = ttk.Frame(ft)
            hints.pack(fill="x")
            self.left_hint = ttk.Label(hints, text="", style="Hint.TLabel")
            self.left_hint.pack(side="left")
            self.right_hint = ttk.Label(hints, text="", style="Hint.TLabel")
            self.right_hint.pack(side="right")

            nudge = ttk.Frame(ft)
            nudge.pack(fill="x", pady=(10, 0))
            for delta, label in ((-10, "\u221210"), (-1, "\u22121"),
                                 (1, "+1"), (10, "+10")):
                ttk.Button(
                    nudge, text=label, width=4,
                    command=lambda d=delta: self._nudge(d),
                ).pack(side="left", padx=(0, 4))
            ttk.Button(
                nudge, text="Reset", command=self._reset_offset
            ).pack(side="right")

            ttk.Separator(outer, orient="horizontal").pack(fill="x")

            hk_frame = ttk.Frame(outer, padding=(0, 14))
            hk_frame.pack(fill="x")
            ttk.Label(hk_frame, text="Toggle hotkey",
                      style="Section.TLabel").pack(anchor="w")
            ttk.Label(
                hk_frame,
                text="A global key combination that toggles the layout.",
                style="Sub.TLabel",
            ).pack(anchor="w", pady=(2, 8))

            row = ttk.Frame(hk_frame)
            row.pack(fill="x")
            self.hk_value_var = tk.StringVar()
            ttk.Label(row, textvariable=self.hk_value_var,
                      style="HotKey.TLabel").pack(side="left")
            self.hk_btn = ttk.Button(row, text="Record\u2026",
                                     command=self._toggle_record)
            self.hk_btn.pack(side="right")
            ttk.Button(row, text="Clear",
                       command=self._clear_hotkey).pack(side="right", padx=(0, 6))
            ttk.Label(
                hk_frame,
                text="Combine modifiers (\u2318/\u2325/\u2303/\u21e7) with one key.",
                style="Hint.TLabel",
            ).pack(anchor="w", pady=(6, 0))

            ttk.Separator(outer, orient="horizontal").pack(fill="x")

            perm_frame = ttk.Frame(outer, padding=(0, 14))
            perm_frame.pack(fill="x")
            ttk.Label(perm_frame, text="Permissions",
                      style="Section.TLabel").pack(anchor="w")
            ttk.Label(
                perm_frame,
                text="The hotkey listener needs Accessibility "
                     "(and on some macOS versions Input Monitoring) "
                     "permission for the Python binary.",
                style="Sub.TLabel",
                wraplength=460,
                justify="left",
            ).pack(anchor="w", pady=(2, 6))

            self.perm_status_var = tk.StringVar()
            ttk.Label(perm_frame, textvariable=self.perm_status_var,
                      style="HotKey.TLabel").pack(anchor="w")

            ttk.Label(
                perm_frame,
                text=str(python_binary()),
                style="Hint.TLabel",
                wraplength=460,
                justify="left",
            ).pack(anchor="w", pady=(2, 8))

            perm_buttons = ttk.Frame(perm_frame)
            perm_buttons.pack(fill="x")
            ttk.Button(perm_buttons, text="Request prompt",
                       command=lambda: request_trust(prompt=True)).pack(side="left")
            ttk.Button(perm_buttons, text="Reveal binary",
                       command=reveal_python_in_finder).pack(side="left", padx=(6, 0))
            ttk.Button(perm_buttons, text="Accessibility\u2026",
                       command=open_accessibility_settings).pack(side="left", padx=(6, 0))
            ttk.Button(perm_buttons, text="Input Monitoring\u2026",
                       command=open_input_monitoring_settings).pack(side="left", padx=(6, 0))

            ttk.Separator(outer, orient="horizontal").pack(fill="x")

            la_frame = ttk.Frame(outer, padding=(0, 14))
            la_frame.pack(fill="x")
            ttk.Label(la_frame, text="Run at login",
                      style="Section.TLabel").pack(anchor="w")
            ttk.Label(
                la_frame,
                text="Installs a launchd agent that launches the menu bar app at login\nand keeps it running in the background.",
                style="Sub.TLabel",
                justify="left",
            ).pack(anchor="w", pady=(2, 8))

            la_row = ttk.Frame(la_frame)
            la_row.pack(fill="x")
            self.la_status_var = tk.StringVar()
            ttk.Label(la_row, textvariable=self.la_status_var,
                      style="Sub.TLabel").pack(side="left")
            self.la_btn = ttk.Button(la_row, text="\u2026",
                                     command=self._toggle_launch_agent)
            self.la_btn.pack(side="right")

            ttk.Separator(outer, orient="horizontal").pack(fill="x")

            self.status = ttk.Label(outer, text="", style="Status.TLabel")
            self.status.pack(anchor="w", pady=(12, 0))

            bottom = ttk.Frame(outer)
            bottom.pack(side="bottom", fill="x", pady=(12, 0))
            ttk.Button(bottom, text="Close",
                       command=self._on_close).pack(side="right")

            self._refresh_hotkey_label()
            self._refresh_la_label()
            self._refresh_perm_label()
            self.after(2000, self._tick_perm)

        # -- layout / offset ------------------------------------------

        def _layout_meta(self) -> dict:
            return make_layouts(self.settings)[self.current.get()]

        def _slider_int(self) -> int:
            return int(round(self.slider_var.get()))

        def _update_value_label(self) -> None:
            ft = self._layout_meta()["fine_tune"]
            self.ft_value.configure(
                text=f"{ft['value_label']}: {self._slider_int()} px"
            )

        def _on_layout_change(self, apply: bool) -> None:
            layout = self._layout_meta()
            self.subtitle.configure(text=layout["subtitle"])
            ft = layout["fine_tune"]

            self.ft_label.configure(text=ft["label"])
            self.left_hint.configure(text=f"\u2190  {ft['left_hint']}")
            self.right_hint.configure(text=f"{ft['right_hint']}  \u2192")

            lo, hi = ft["range"]
            self.slider.configure(from_=lo, to=hi)
            self.slider_var.set(self.settings[ft["settings_key"]])
            self._update_value_label()

            if apply:
                self._apply_current()

        def _on_slider_drag(self, _val: str) -> None:
            self._update_value_label()

        def _on_slider_release(self, _evt) -> None:
            ft = self._layout_meta()["fine_tune"]
            new_val = self._slider_int()
            if self.settings[ft["settings_key"]] == new_val:
                return
            self.settings[ft["settings_key"]] = new_val
            save_settings(self.settings)
            self._apply_current()

        def _nudge(self, delta: int) -> None:
            ft = self._layout_meta()["fine_tune"]
            lo, hi = ft["range"]
            new_val = max(lo, min(hi, self.settings[ft["settings_key"]] + delta))
            if new_val == self.settings[ft["settings_key"]]:
                return
            self.settings[ft["settings_key"]] = new_val
            save_settings(self.settings)
            self.slider_var.set(new_val)
            self._update_value_label()
            self._apply_current()

        def _reset_offset(self) -> None:
            ft = self._layout_meta()["fine_tune"]
            default = DEFAULTS[ft["settings_key"]]
            self.settings[ft["settings_key"]] = default
            save_settings(self.settings)
            self.slider_var.set(default)
            self._update_value_label()
            self._apply_current()

        def _apply_current(self) -> None:
            name = self.current.get()
            ft = self._layout_meta()["fine_tune"]
            offset = self.settings[ft["settings_key"]]
            self.status.configure(text=f"Applying \u2018{name}\u2019\u2026")
            self.update_idletasks()
            ok, msg = apply_layout(self.settings, name)
            if ok:
                self.status.configure(
                    text=f"Active: {name}  \u00b7  {ft['value_label']}={offset} px"
                )
            else:
                self.status.configure(text=f"Failed: {msg.splitlines()[0]}")
                messagebox.showerror("displayplacer failed", msg)

        # -- hotkey ----------------------------------------------------

        def _refresh_hotkey_label(self) -> None:
            hk = self.settings.get("hotkey", "")
            self.hk_value_var.set(pretty_hotkey(hk) or "(not set)")

        def _toggle_record(self) -> None:
            if self.recording:
                self._stop_record()
            else:
                self._start_record()

        def _start_record(self) -> None:
            self.recording = True
            self.hk_btn.configure(text="Listening\u2026 (Esc to cancel)")
            self.hk_value_var.set("\u2026 press keys")
            self._held_mods = []
            self.focus_force()

        def _stop_record(self) -> None:
            self.recording = False
            self._held_mods = []
            self.hk_btn.configure(text="Record\u2026")

        def _cancel_record(self) -> None:
            self._stop_record()
            self._refresh_hotkey_label()

        def _on_keypress(self, event):
            if not self.recording:
                return None

            sym = event.keysym
            if sym in HELD_MOD_KEYSYMS:
                mod = HELD_MOD_KEYSYMS[sym]
                if mod not in self._held_mods:
                    self._held_mods.append(mod)
                return "break"

            if sym == "Escape":
                self._cancel_record()
                return "break"

            key_token = keysym_to_token(sym)
            if key_token is None:
                self.status.configure(
                    text=f"Unsupported key: {sym!r} \u2014 try another"
                )
                self.hk_value_var.set(f"{sym}? press another key")
                return "break"

            mods = sorted(
                set(self._held_mods),
                key=lambda m: MOD_ORDER.index(m) if m in MOD_ORDER else 99,
            )
            mod_str = "+".join(f"<{m}>" for m in mods)
            hk = f"{mod_str}+{key_token}" if mod_str else key_token

            ok, err = validate_hotkey(hk)
            if not ok:
                self.status.configure(
                    text=f"pynput can't bind {sym!r}: {err}"
                )
                self.hk_value_var.set("press another key")
                return "break"

            self._save_hotkey(hk)
            return "break"

        def _on_keyrelease(self, event):
            if not self.recording:
                return None
            sym = event.keysym
            if sym in HELD_MOD_KEYSYMS:
                mod = HELD_MOD_KEYSYMS[sym]
                if mod in self._held_mods:
                    self._held_mods.remove(mod)
            return None

        def _save_hotkey(self, hk: str) -> None:
            self._stop_record()
            self.settings["hotkey"] = hk
            save_settings(self.settings)
            self._refresh_hotkey_label()
            self.status.configure(text=f"Hotkey set: {pretty_hotkey(hk)}")

        def _clear_hotkey(self) -> None:
            self.settings["hotkey"] = ""
            save_settings(self.settings)
            self._refresh_hotkey_label()
            self.status.configure(text="Hotkey cleared")

        # -- permissions ------------------------------------------------

        def _refresh_perm_label(self) -> None:
            if is_trusted():
                self.perm_status_var.set("Accessibility: granted \u2714")
            else:
                self.perm_status_var.set(
                    "Accessibility: not granted \u2716  "
                    "(hotkey will not fire)"
                )

        def _tick_perm(self) -> None:
            self._refresh_perm_label()
            self.after(2000, self._tick_perm)

        # -- launch agent ----------------------------------------------

        def _refresh_la_label(self) -> None:
            if launch_agent_installed():
                self.la_status_var.set("Installed \u2014 starts at login.")
                self.la_btn.configure(text="Uninstall")
            else:
                self.la_status_var.set("Not installed.")
                self.la_btn.configure(text="Install")

        def _toggle_launch_agent(self) -> None:
            if launch_agent_installed():
                ok, msg = uninstall_launch_agent()
                if ok:
                    self.status.configure(text="Launch agent uninstalled")
                else:
                    messagebox.showerror("Uninstall failed", msg)
            else:
                ok, msg = install_launch_agent()
                if ok:
                    self.status.configure(
                        text=f"Launch agent installed at {msg}"
                    )
                else:
                    messagebox.showerror("Install failed", msg)
            self._refresh_la_label()

        # -- close ------------------------------------------------------

        def _on_close(self) -> None:
            self._stop_record()
            self.destroy()

    App().mainloop()


# ===== CLI ===============================================================

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--config", action="store_true",
                       help="Open settings window")
    group.add_argument("--toggle", action="store_true",
                       help="Toggle layout once and exit")
    group.add_argument("--install-agent", action="store_true",
                       help="Install launchd agent (start at login)")
    group.add_argument("--uninstall-agent", action="store_true",
                       help="Remove launchd agent")
    group.add_argument("--restart", action="store_true",
                       help="Restart the running launchd agent")
    group.add_argument("--status", action="store_true",
                       help="Print diagnostic info and exit")
    args = parser.parse_args()

    if args.config:
        run_config_window()
    elif args.toggle:
        settings = load_settings()
        current, _, _ = detect_state()
        if current not in ("above", "right"):
            current = "above"
        new = "right" if current == "above" else "above"
        ok, msg = apply_layout(settings, new)
        if not ok:
            sys.exit(f"Toggle failed: {msg}")
        print(f"Switched to {new}")
    elif args.install_agent:
        ok, msg = install_launch_agent()
        if ok:
            print(f"Installed: {msg}")
        else:
            sys.exit(f"Install failed: {msg}")
    elif args.uninstall_agent:
        ok, msg = uninstall_launch_agent()
        if ok:
            print("Uninstalled.")
        else:
            sys.exit(f"Uninstall failed: {msg}")
    elif args.restart:
        ok, msg = restart_launch_agent()
        if ok:
            print("Launch agent restarted.")
        else:
            sys.exit(f"Restart failed: {msg}")
    elif args.status:
        print_status()
    else:
        run_menu_bar_app()


if __name__ == "__main__":
    main()
