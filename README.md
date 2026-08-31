# Desktop Gremlin

One to ten chaotic stick figures who live **on top of** your real Windows
desktop and treat your actual icons and open windows as their personal
playground.

They aren't a wallpaper. A wallpaper sits *behind* your icons and can't see
them. This lot sit above everything and read the real thing — where your icons
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

Then double-click **`run_gremlin.bat`**. It installs `pywin32` the first time,
launches them with `pythonw`, and closes itself - there is no console window
left behind to keep open. Quit from the tray icon.

Or by hand:

```
pip install -r requirements.txt
python desktop_gremlin.py
```

Everything lives on the **tray icon**, bottom-right: Settings, Pause, Bring
them to my cursor, Restore my icon layout, Quit. Right-clicking a gremlin also
opens Settings.

Running `python desktop_gremlin.py` by hand keeps a console, and closing it
kills them - that console is their parent process. Use `pythonw
desktop_gremlin.py` instead, or just use the .bat.

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

Explosions move them too. A bomb or a rocket landing in a cluster shoves every
icon in the blast outward, hardest for whatever was closest; a stray bullet
knocks a single icon aside. All of it is clamped to the visible desktop, and all
of it is undone by **Restore my icon layout**.

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

## The cast

Ten of them, and you choose how many turn up. They join in a fixed order, so
two is always the same two and their records carry over between runs.

| | who | plays like |
|---|---|---|
| 1 | Brawler | charges, melee, loudest thing on screen |
| 2 | Sniper | keeps his distance, ranged, deadpan |
| 3 | Coward | avoids fights, runs when hurt, apologises |
| 4 | Show-off | taunts constantly, rockets and lightning |
| 5 | Grump | slow, quiet, hits hard, complains |
| 6 | Magpie | ignores the others, steals your icons relentlessly |
| 7 | Zealot | never retreats, rage-driven, ignores damage |
| 8 | Tinkerer | bombs, methodical, patient |
| 9 | Drama | over-reacts to everything, sulks longest |
| 10 | Veteran | economical, few words, efficient |

Each has its own colour, its own temperament — how readily it picks a fight,
how much it talks, how fast it moves, how often it jumps, how likely it is to
steal rather than smash, and how much punishment it takes before breaking off
— and its own dialogue, right down to what it says when you pick it up. No two
of them share a line.

It's a free-for-all: everyone goes for whoever is nearest. They chase, strike,
knock each other flying, with a deliberate beat between strikes so a fight is
something you can follow rather than a blur. Take enough hits and you're
knocked out — X eyes, flat on your back — then up again a few seconds later,
furious about it. A health bar appears over whoever's hurt.

Set `crowd` to anything from 1 to 10.

## They remember you

Between runs, in `gremlin_memory.json`. Each character keeps its own count of
how often you've grabbed it, how often you've thrown it, its win-loss record
against the others, and how many icons it has made off with. A few seconds
after launch one of them will bring it up — *"you've thrown me 41 times"*,
*"{wins} and {losses}, I'm rounding up"* — and a losing streak makes that one
come back keener, with a different line for it.

They also develop a grudge against whichever icon they have picked on most, and
greet it by name.

**Counters, never a log.** Nothing about which applications or windows you use
is written to disk. The only names stored are desktop icon labels, which
`gremlin_icon_backup.json` already holds. **Settings → Make them forget
everything about me** wipes it, and so does deleting the file.

## They notice what you're doing

In memory only, never written down. Twelve window switches in a minute, fifteen
minutes staring at one thing, three hours at the desk, the small hours, an
unsaved-changes marker in a title bar:

> *pick ONE* · *blink. please blink.* · *go to BED* · *SAVE IT*

Each remark has its own five-to-thirty-minute cooldown on top of a global
two-minute one, and nothing fires in the first 45 seconds. The difference
between a desktop pet you keep and one you uninstall is how often it decides to
be clever at you.

Turn the lot off with **react_to_windows**.

## Moods

**bored → hyped → furious → smug → sulking**, and asleep.

The figures themselves are black. Mood is the **halo round the head** — amber
when hyped, red when furious, dim when asleep — plus posture and the face, which
is drawn light so you can actually read it. Every mood has its own eyes and
mouth: furious brows, a hyped grin, a smug smirk, X eyes when knocked out.

The halo tells you who as well as how they feel: each character shifts its own
base colour through the moods, so the Brawler's furious is not the Sniper's.

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

They can leave the screen, and come back on the other side of it. Walk off the
right edge, reappear on the left. It happens when one gets knocked out of view,
and it stops a fight drifting off the edge and carrying on where you cannot see
it — anyone out of sight for more than a moment is brought back round.

---

## Files it writes

All of them sit next to the script, and every one is safe to delete.

| File | What |
|---|---|
| `gremlin_settings.json` | your settings; delete for defaults |
| `gremlin_icon_backup.json` | your icon layout as it was on first run — the undo |
| `gremlin_memory.json` | what they remember about you |
| `gremlin.ico` | the tray icon, rebuilt each launch |
| `gremlin_log.txt` | only written when there is no console; see below |

## Settings

`gremlin_settings.json`, written by the Settings window. Delete it for defaults.

| Key | Default | |
|---|---|---|
| `scale` | `0.68` | 0.68 = the height of a desktop icon |
| `fps` | `40` | |
| `chaos` | `1.0` | how fast they escalate; scales icon-stealing too |
| `crowd` | `2` | how many of them, 1 to 10 |
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
  moving between folders, no deleting. Explosions shove icons around the
  desktop, but that is still only a position, and **Restore my icon layout**
  puts every one of them back. All of it needs *Let them actually drag my
  desktop icons*, which is off until you turn it on.
- **What they remember is counters.** Grabs, throws, wins, losses, icons moved,
  and the labels of the desktop icons they pick on — nothing about which
  applications or windows you use, and nothing leaves your machine. Everything
  they notice about your working habits lives in memory and dies with the
  process. *Settings → Make them forget everything about me*, or delete
  `gremlin_memory.json`.
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

## If something goes wrong

Launched from the `.bat` there is no console, so nothing can print an error at
you. Anything that goes wrong is written to **`gremlin_log.txt`** next to the
script instead, and the tray icon pops a balloon once to say so. That file is
the first place to look, and the right thing to attach to an issue.

```
run_gremlin.bat --debug
```

Debug keeps the console window and draws the collision geometry: green lines
are icon platforms, blue are window title bars, red is the floor. If they don't
line up with your real icons, that's a DPI problem — open an issue with a
screenshot.

## Checking a change

```
python tests\run_all.py
```

Twelve checks, a couple of seconds, nothing to install. They drive the real app
with the Windows shell stubbed out, so they never touch your desktop. Every one
of them encodes a bug that actually shipped.

---

## License

MIT — see [LICENSE](LICENSE).
