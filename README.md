# Desktop Gremlin

Two chaotic stick figures who live **on top of** your real Windows desktop and
treat your actual icons and open windows as their personal playground.

They aren't a wallpaper. A wallpaper sits *behind* your icons and can't see
them. These two sit above everything and read the real thing — where your icons
are and what they're called, where your windows are, which one you just
clicked, whether you're even at the keyboard.

Then they climb on all of it, and fight each other.

![Every pose and weapon](docs/poses.png)

---

## Install

Needs **Windows** and **Python 3.8+** ([python.org](https://www.python.org/downloads/) —
tick *Add python.exe to PATH* during setup).

```
git clone https://github.com/mbwallace1390/desktop-gremlin.git
cd desktop-gremlin
```

Then double-click **`run_gremlin.bat`**. It installs `pywin32` the first time
and launches them.

Or by hand:

```
pip install -r requirements.txt
python desktop_gremlin.py
```

Everything lives on the **tray icon**, bottom-right: Settings, Pause, Bring
them to my cursor, Restore my icon layout, Quit. Right-clicking a gremlin also
opens Settings.

Want no console window? `pythonw desktop_gremlin.py`, or tick *Start with
Windows* in Settings.

---

## What they actually read

| Thing | How |
|---|---|
| Desktop icon positions and names | `LVM_GETITEMRECT` / `LVM_GETITEMTEXT` on the shell's `SysListView32` |
| Open windows | `EnumWindows` + `DwmGetWindowAttribute` for the true visual frame |
| Which window you're using | `GetForegroundWindow` |
| Whether you're there | `GetLastInputInfo` |
| Where the floor is | per-monitor work area, so they stand *on* your taskbar |

Rescanned every 1.6 seconds. Icon tops and window title bars become platforms.
Drag a window across the screen and whoever's standing on it rides along.

---

## They can move your actual icons

Off by default. Turn it on in **Settings → *Let them actually drag my desktop
icons***.

With it on, one of them beats up an icon, hoists it over their head, carries it
across the desktop and drops it somewhere else — and your icon is genuinely
there now. Not an animation of an icon. The icon.

**The undo:** your layout is written to `gremlin_icon_backup.json` the first
time you ever run this. **Tray → Restore my icon layout** puts every icon back.

Safety rules, in the code:

- If that backup can't be written, icon dragging is **forced off** for the run.
  They never move anything that can't be put back.
- If your desktop has **Auto arrange icons** on, Windows snaps everything back
  instantly. The app detects this and says so on startup.
- Icons are always dropped inside the visible desktop, never off-screen.

Roughly a couple of icons every five minutes at default chaos.

---

## The two of them

The second one is pink. They chase each other, strike, knock each other flying,
and there's a deliberate beat between strikes so a fight is something you can
follow rather than a blur. Take enough hits and you're knocked out — X eyes,
flat on your back — then up again a few seconds later, furious about it. A
health bar appears over whoever's hurt.

Set `rival: false` if you'd rather have one.

## Moods

**bored → hyped → furious → smug → sulking**, in colour, posture and face.
Left alone too long, boredom curdles into a rampage. They also flare up for no
reason. Once you've been away five minutes they curl up and sleep.

## Loadout

Sword and chainsaw up close. Bow, laser blaster, minigun, rocket launcher and a
lightning gun at range. Bombs when they're feeling expressive. Grapple gun for
getting around.

## Playing with them

Move your cursor near one — two rings appear, that's the grab target. Click,
drag, throw. They tumble, land, and hold a grudge. They notice your cursor from
anywhere on screen and sometimes come pick a fight with it.

Everywhere else the overlay is click-through, so it never intercepts your work.

---

## Settings

`gremlin_settings.json`, written by the Settings window. Delete it for defaults.

| Key | Default | |
|---|---|---|
| `scale` | `0.68` | 0.68 = the height of a desktop icon |
| `fps` | `40` | |
| `chaos` | `1.0` | how fast they escalate; scales icon-stealing too |
| `rival` | `true` | spawn the second one |
| `move_icons` | `false` | let them physically drag your icons |
| `react_to_windows` | `true` | comment on window titles, follow focus |
| `sleep_when_idle` | `true` | |
| `idle_minutes` | `5.0` | |
| `all_monitors` | `true` | restart to apply |
| `start_with_windows` | `false` | adds a `Run` key entry |

---

## Caveats

- **Your files are never touched.** The only thing that physically changes is
  where a desktop icon *sits* — a position, nothing else. No renaming, no
  moving between folders, no deleting. The explosions are animation.
- **Reading icon positions** means asking Explorer's list control where its
  items are, which needs a read-only buffer inside the Explorer process
  (`VirtualAllocEx` + `ReadProcessMemory`). It's the standard technique — every
  "save my icon layout" utility does the same — but an aggressive antivirus may
  ask about it. It only ever reads.
- **Fullscreen games** cover them, which is usually what you want.
- Multi-monitor works; turn it off to keep them on the primary screen.

---

## How it works

A single always-on-top `tkinter` window covering the virtual screen, made
invisible and click-through by keying one exact colour (`#010101`) via
`SetLayeredWindowAttributes`. Anything drawn in that colour is both invisible
and passes mouse clicks through; anything else is visible and clickable — which
is why the grab rings are the hit target.

The figures are drawn procedurally, not from sprites: a skeleton with two-bone
IK for the arms and legs, posed per state, then squashed and mirrored. That's
why they scale cleanly from icon-sized to huge, and why adding a weapon is a
dozen lines rather than a spritesheet.

Physics is one-way platforms with a ledge-grab pass. Every motion constant is
multiplied by a scale factor derived from body size, so a small gremlin moves
like a small thing rather than a slowed-down big one.

## Debug

```
run_gremlin.bat --debug
```

Green lines are icon platforms, blue are window title bars, red is the floor.
If they don't line up with your real icons, that's a DPI problem — open an
issue with a screenshot.

---

## License

MIT — see [LICENSE](LICENSE).
