# Screen Layout Switcher

A macOS menu bar app that flips your HDMI external display between two
saved layouts:

- **Above** — external sits above the MacBook.
- **Right** — external sits to the right of the MacBook.

Features:

- Menu bar icon that always shows the active layout (▲ or ▶).
- Per-layout fine-tune offset slider so you can align screens to their
  physical positions and stop the cursor from jumping when crossing.
- Configurable global hotkey (`⌘⌥⌃R` by default) that toggles layouts.
- Optional launchd agent that starts the app at login and keeps it
  running 24/7.
- All settings persist in `~/.screen_switcher.json`.

## One-time setup

```bash
cd /Users/vincentrost/Desktop/screen-setup
./setup.sh
```

`setup.sh` installs `displayplacer`, `python-tk@3.14`, creates a
`.venv/`, and installs `rumps` + `pynput`.

## Run

```bash
.venv/bin/python screen_switcher.py
```

A small ▲ or ▶ glyph appears in the menu bar. Click it to:

- Switch directly to **Above** or **Right**
- Use **Toggle** to flip
- Open **Settings…** for the offset sliders, hotkey recorder, and
  launch-agent toggle
- **Quit**

## Settings window

Open it from the menu bar or via:

```bash
.venv/bin/python screen_switcher.py --config
```

Sections:

1. **Layout** — radio buttons mirror the menu bar.
2. **Fine-tune alignment** — slider that controls the MacBook's offset
   relative to the external. The slider repurposes itself for the
   active layout (horizontal in *Above*, vertical in *Right*). Drag and
   release to apply; `±1`/`±10` buttons for pixel-precise nudges.
3. **Toggle hotkey** — click *Record…*, then press a key combination
   (e.g. ⌘⌥⌃R). Press *Esc* to cancel. *Clear* unbinds the hotkey.
4. **Run at login** — install/uninstall the launchd agent.

## Hotkey & permissions

`pynput` listens for global key events, which on macOS requires
**Input Monitoring** permission. The first time the listener runs:

1. macOS will prompt — grant permission for the Python binary
   (`.venv/bin/python` or `/opt/homebrew/opt/python@3.14/bin/python3.14`).
2. If you missed the prompt, open
   *System Settings → Privacy & Security → Input Monitoring*
   and add the Python binary manually.

Same applies to **Accessibility** for some macOS versions. Granting both
is the safest bet.

## Run at login (launchd agent)

Either click *Install* in the settings window, or run:

```bash
.venv/bin/python screen_switcher.py --install-agent
```

This writes
`~/Library/LaunchAgents/com.vincentrost.screenswitcher.plist` and loads
it. The agent is configured with `RunAtLoad=true` and `KeepAlive=true`
so the menu bar app starts at login and gets restarted if it ever
crashes. Logs are written to `screen_switcher.log` next to the script.

To uninstall:

```bash
.venv/bin/python screen_switcher.py --uninstall-agent
```

## CLI reference

```bash
screen_switcher.py                # menu bar app (default)
screen_switcher.py --config       # open settings window
screen_switcher.py --toggle       # one-shot toggle, exits
screen_switcher.py --install-agent
screen_switcher.py --uninstall-agent
screen_switcher.py --restart      # restart the launchd agent
screen_switcher.py --status       # diagnostic dump (settings, perms, agent, log)
```

`--toggle` is handy if you want to bind the toggle to a different
launcher (Raycast, Alfred, BetterTouchTool…) without using the
built-in pynput hotkey.

## Recovery & troubleshooting

The launch agent is configured with `RunAtLoad=true`, `KeepAlive=true`,
and `ThrottleInterval=10`, which means **launchd will start the app at
login and re-spawn it within 10 seconds of any crash**, indefinitely.
That covers the common cases automatically; the steps below are for
when something deeper has gone wrong.

### First step: ask the app what it thinks

```bash
.venv/bin/python screen_switcher.py --status
```

This prints settings, current layout, Accessibility trust state, the
launch agent's PID/last exit code, and a tail of the log. 90% of issues
become obvious here.

### Cheat sheet

| Symptom                                     | Fix                                                                                       |
| ------------------------------------------- | ----------------------------------------------------------------------------------------- |
| App not in menu bar after login             | `.venv/bin/python screen_switcher.py --status` → if `loaded: False`, run `--install-agent` |
| Menu bar icon disappeared mid-session       | `.venv/bin/python screen_switcher.py --restart`                                            |
| Hotkey stopped firing                       | Check `Accessibility trust` in `--status`; re-grant if missing                              |
| Anything weird                              | `tail -f screen_switcher.log` while reproducing                                              |
| Want a clean reload                         | `--uninstall-agent`, then `--install-agent`                                                  |
| Just want to start the app once, no agent   | `.venv/bin/python screen_switcher.py`                                                       |

### What "boot start doesn't work" usually means

Most likely cause, in order:

1. **The agent isn't installed.** `--status` will say `installed: False`.
   Run `--install-agent`.
2. **Homebrew Python was upgraded.** The venv contains absolute paths
   to a specific Python build (e.g. `python@3.14/3.14.4_1`). When brew
   replaces it with `3.14.5_1`, the venv breaks. Recreate it:
   ```bash
   rm -rf .venv && ./setup.sh
   .venv/bin/python screen_switcher.py --install-agent
   ```
3. **Accessibility was revoked.** Same Python upgrade can also wipe the
   Accessibility grant (macOS keys it to the binary path). Re-add the
   binary in *System Settings → Privacy & Security → Accessibility*.
4. **`displayplacer` not in PATH.** The agent's plist sets
   `PATH=/opt/homebrew/bin:…`. If you've moved Homebrew, reinstall the
   agent so the plist regenerates with current paths.

### Manual `launchctl` (advanced)

If you'd rather drive launchd directly:

```bash
LABEL=com.vincentrost.screenswitcher
PLIST=~/Library/LaunchAgents/$LABEL.plist

launchctl print gui/$(id -u)/$LABEL          # full state dump
launchctl kickstart -k gui/$(id -u)/$LABEL   # force restart
launchctl bootout  gui/$(id -u)/$LABEL       # stop and unload
launchctl bootstrap gui/$(id -u) "$PLIST"    # load
```

### Logs

Combined stdout / stderr go to `screen_switcher.log` (next to the
script). It rotates only when you delete it, so check size occasionally:

```bash
tail -f screen_switcher.log
ls -lh screen_switcher.log
```

## Display IDs

Hardcoded near the top of `screen_switcher.py`:

| Display          | Persistent ID                          |
| ---------------- | -------------------------------------- |
| External HDMI    | `DD110D51-7707-4A87-98E1-AEAA88626864` |
| MacBook built-in | `37D8832A-2D66-02CA-B9F7-8F30A301B230` |

If you change monitor or HDMI dongle, run `displayplacer list` and
update the constants.
