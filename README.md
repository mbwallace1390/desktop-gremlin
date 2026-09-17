# Desktop Gremlin

One to ten chaotic stick figures who live **on top of** your real desktop.
Windows supports Explorer icons and open windows. Linux X11 supports open
windows and the desktop floor, including climbing, dragging gremlins and
optional window nudges with restoration.

**3.2.1 performance:** less repeated crate geometry and collision work, faster
icon-recovery lookups, bounded waits for busy Windows Explorer, and clearer
performance readings. Controlled hidden-window Windows measurements found
21–50% less CPU work in crowded toy scenes; these are not visible-desktop FPS
claims. See the [measurements and verification](docs/PERFORMANCE.md).

**3.2.0 physics:** momentum-aware hits and blasts, directional bounces,
constrained ragdoll limbs during grabs, throws and knockouts, smoother mouse
throws, moving crates, weighted seesaws, swept body/window-edge contacts,
moving-anchor swings, and selectable gravity and surface feel. See the
[physics guide](PHYSICS_GUIDE.md) for controls and the simulation's limits.

**3.1.0:** Linux X11 desktop support and bundled Windows/Linux downloads.
Wayland sessions and Linux desktop icon rearrangement are not supported.

**3.0.0 expansion:** seven new weapons, parkour and playground toys, friendships
and staged group scenes, a custom cast and three play modes. See the
[feature guide](EXPANSION_GUIDE.md) for the complete list and controls.

The additions are a returning **boomerang**, **bubble** cannon, **freeze** ray,
**swap** gun, boxing **glove**, ricocheting **rubber** balls and sticky **foam**.

Windows native rendering remains disabled after a desktop input
regression. Normal startup uses Tk, including with older saved settings.
Linux uses the same Tk drawing with X11 shapes that pass empty-space clicks
through to the application underneath.
**Ctrl+Alt+Shift+Q** exits Gremlin without using the mouse (when the shortcut
registers successfully). Animation, visibility and engine improvements remain.

They aren't a wallpaper. A wallpaper sits *behind* your icons and can't see
them. This lot sit above everything and read the real thing — where your icons
are and what they're called, where your windows are, which one you just
clicked, whether you're even at the keyboard.

Then they climb on all of it, and fight each other.

![Weapons, playground toys and group scenes drawn by the Tk app](docs/expansion-preview.svg)

*Actual app drawing staged on simulated terrain in a hidden Tk window.*

---

## Download and run

Both releases include Python, Tk and required application libraries. End users
install no Python or pip packages. Linux needs an x64 glibc desktop compatible
with Ubuntu 22.04 or newer and an X11 session.

1. Open [GitHub Releases](https://github.com/mbwallace1390/desktop-gremlin/releases).
2. Under the release's **Assets**, download **DesktopGremlin-3.2.1-Windows-x64.zip**.
3. Right-click the ZIP, choose **Extract All**, then open the extracted folder.
4. Double-click **DesktopGremlin.exe**. Keep its `_internal` folder beside it.

Choose the executable archive under the release's Assets. GitHub's **Source code**
downloads are for developers.
See [the download guide](USER_DOWNLOAD_GUIDE.md) for updating and uninstalling.

On Linux, download **DesktopGremlin-3.2.1-Linux-x64.tar.gz**, extract it, and
open **DesktopGremlin** inside the extracted folder. Keep `_internal` beside
it. A small control window provides Settings, Performance, Pause, Bring them
to my cursor, Put my windows back, and Quit. Right-click a gremlin to show it.
See [Linux download instructions](USER_DOWNLOAD_LINUX.md).

GitHub Actions builds both native packages and prepares a draft release only
after both pass. Published downloads appear under Releases → Assets.
See [build instructions](packaging/BUILDING.md).

## Run from source (developers)

Windows needs **Python 3.8+** ([python.org](https://www.python.org/downloads/) —
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

Linux developers need Python 3.8+, Tk and X11/SHAPE system libraries. Run
`python3 desktop_gremlin.py` in an X11 session. See
[Linux build and test instructions](packaging/LINUX_BUILDING.md).
Linux settings and memory live in `$XDG_DATA_HOME/DesktopGremlin` or
`~/.local/share/DesktopGremlin`. The optional login entry is stored at
`$XDG_CONFIG_HOME/autostart/DesktopGremlin.desktop` (normally `~/.config`).

Everything lives on the **tray icon**, bottom-right: Settings, Performance, Pause, Bring
them to my cursor, Restore my icon layout, Put my windows back, Quit.
Right-clicking a gremlin also opens Settings.

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

Rescanned every 1.6 seconds, on a thread of its own so a busy Explorer never
stalls the animation. Occupied windows are also tracked up to 30 times a second
so their passengers follow while you drag. Icon tops and window title bars
become platforms.

---

## They can move your actual icons

Off by default. Turn it on in **Settings → *Let them actually drag my desktop
icons***.

With it on, one of them beats up an icon, hoists it over their head, carries it
across the desktop and drops it somewhere else — and your icon is genuinely
there now. Not an animation of an icon. The icon.

Explosions move them too. A bomb or a rocket landing in a cluster shoves every
icon in the blast outward, hardest for whatever was closest; a bullet that
strikes an icon knocks it aside. By default stray fire — shots meant for
another fighter, your cursor, or a window — passes over the desktop rather
than being soaked up by whatever icon stood in the way; turn
`shots_over_icons` off if you want the icons to serve as cover. All of it is
clamped to the visible desktop, and all of it is undone by **Restore my icon
layout**.

**The undo:** your layout is written to `gremlin_icon_backup.json` every time
you launch, so **Tray → Restore my icon layout** puts every icon back where it
was when this run started — not where it was months ago when you first tried
this. The one exception: if the last run moved icons and never put them back
(a crash, or a quit with the desktop still scattered), that older snapshot is
the good one, and it is kept until you restore. The very first layout ever
seen stays in the file as `first`, and the last three launches as `previous`,
for recovery by hand.

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

The figures share a dark body by default; choose light bodies and optional
contrast outlines in Settings for a dark desktop. Each one has its own **halo colour**, its
own temperament — how readily it picks a fight, how much it talks, how fast it
moves, how often it jumps, how likely it is to steal rather than smash, and how
much punishment it takes before breaking off — and its own dialogue, right down
to what it says when you pick it up. No two of them share a line.

Rivals draw their attention, friends can help, and temporary allies team up
against the strongest gremlin. They chase, strike,
knock each other flying, with a deliberate beat between strikes so a fight is
something you can follow rather than a blur. Take enough hits and you're
knocked out — X eyes, flat on your back — then up again a few seconds later,
furious about it. A health bar appears over whoever's hurt. Tick `blood` in
Settings if you want the cartoon red to match: sprays on hits, stains on the
floor that fade on their own — or get mopped up by a water balloon. Only they
bleed; your icons still just spark.

Set `crowd` to anything from 1 to 10, or choose exactly who joins in the Cast tab.

## They remember you

Between runs, in `gremlin_memory.json`. Each character keeps its own count of
how often you've grabbed it, how often you've thrown it, its win-loss record
against the others, and how many icons it has made off with. A few seconds
after launch one of them will bring it up — *"you've thrown me 41 times"*,
*"{wins} and {losses}, I'm rounding up"* — and a losing streak makes that one
come back keener, with a different line for it.

They also develop a grudge against whichever icon they have picked on most, and
greet it by name. Friendships and rivalries are stored as 45 possible numeric
scores between the ten character identities. Custom nicknames stay in settings.

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

Mood is the **halo round the head** — amber
when hyped, red when furious, dim when asleep — plus posture and the face, which
automatically contrasts with the selected body colour. Every mood has its own eyes and
mouth: furious brows, a hyped grin, a smug smirk, X eyes when knocked out.

The halo tells you who as well as how they feel: each character shifts its own
base colour through the moods, so the Brawler's furious is not the Sniper's.

Left alone too long, boredom curdles into a rampage. They also flare up for no
reason. Once you've been away five minutes they curl up and sleep.

## Loadout

Sword, chainsaw, a giant fish and a frying pan up close — the pan can bat an
incoming round straight back at whoever fired it. Bow, laser blaster, minigun,
rocket launcher and a lightning gun at range. Bombs when they're feeling
expressive, and a blackhole grenade that pulls everything *inward* instead.
A harpoon that reels the other one in, a magnet that drags your icons over. An
anvil and a piano delivered from the sky onto a marked spot. A banana peel and
a springboard placed on the ground and sprung by whoever steps there — owner
included. And for the soft-hearted: a confetti cannon whose ammunition is a
mood (the victim comes out *delighted*), and water balloons that put a fight
out on the spot.

## Getting around

The grapple gun is no longer the only way to travel, and not everything they
do is a fight — a bored gremlin is as likely to take a joyride or wander over
to bother a colleague. Depending on who: a pogo stick, a skateboard, a balloon
ride (poppable, and the sniper knows it), a self-launching
cannon, a jetpack that wobbles its way to a cruising height and then runs out
of tank, riding on another one's shoulders, or surfing across the desktop
standing on one of your actual icons — that last one obeys the same
`move_icons` switch as dragging, and never happens without the layout backup.
The nervous ones deploy a parachute on long falls. The grump rides nothing.

For elevated targets they can plan short routes over reachable platforms,
using jumps and climbs. Moving platforms invalidate the route; failed steps
get a cooldown so they do not keep attempting the same blocked approach.

## Playing with them

Move your cursor near one — two rings appear and a name tag says which one
you're about to grab. Click, drag, throw. They tumble, land, and hold a
grudge. They notice your cursor from
anywhere on screen and sometimes come pick a fight with it.

Everywhere else the overlay is click-through, so it never intercepts your work.

## They play on your windows

The window you are working in is a climbing frame. One will sit on its title
bar with legs dangling, kick its feet, lie back, doze off. Another hangs from
the bottom edge by the hands and swings, with the odd pull-up. The nervy ones
cling to a side edge and peek round it, or climb it hand over hand and sit on
the top. The loud ones bang on the glass, lean on it, press a face against it.
Each has its own repertoire; the grump only ever leans. Other windows get
visits too, but the one with the focus gets most of them, and a maximised
window has no edges to hang off.

Bring your cursor towards one on a window and it scrambles off, so your click
on a title-bar button, a scrollbar or an edge gets through. Stop the cursor on
one and the grab rings appear as usual.

They never move a window unless you let them. **Settings → *Let them nudge my
windows*** (off by default) allows a shove of a few pixels: a knock ends with
one, and a rocket into a window slides it a little. Never the window you are
typing in, never a maximised one, never off its monitor, never more than a few
a minute. **Tray → Put my windows back** returns every nudged window to where
it was.

They can leave the screen, and come back on the other side of it. Walk off the
right edge, reappear on the left. It happens when one gets knocked out of view,
and it stops a fight drifting off the edge and carrying on where you cannot see
it — anyone out of sight for more than a moment is brought back round.

---

## Files it writes

The packaged app stores these in `%LOCALAPPDATA%\DesktopGremlin`.
Source runs keep them next to the script. Preserve the icon backup until you
have restored any moved icons; deleting it removes that undo information.

| File | What |
|---|---|
| `gremlin_settings.json` | your settings; delete for defaults |
| `gremlin_icon_backup.json` | your icon layout as it was when this run started — the undo |
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
| `cast` | `` | empty uses crowd order; otherwise chosen distinct character identities |
| `profiles` | `{}` | per-character nickname, halo color, hat and optional allowed weapons |
| `play_mode` | `mischief` | peaceful activities, mixed mischief, or frequent battle |
| `group_scenes` | `true` | friendships, rescues, staged comedy and quiet group activities |
| `parkour` | `true` | pendulum swings, wall kicks, rolls, vaults, slides, planes and boosts |
| `toy_props` | `true` | temporary crates, seesaws, ramps, fans and conveyors |
| `physics_preset` | `normal` | normal, moon, bouncy or heavy gravity and impulse response |
| `surface_material` | `standard` | standard, ice, rubber or sticky friction and bounce |
| `renderer` | `tk` | Tk only; older `auto` settings cannot enable native presentation |
| `body_theme` | `dark` | `dark` or `light`, with contrasting faces |
| `halo_strength` | `1.0` | mood halo strength, 0.5 to 2.0 |
| `outline` | `false` | contrast outlines around limbs and body |
| `effects_quality` | `1.0` | decorative particle detail, 0.25 to 1.0 |
| `auto_quality` | `true` | reduce decorative detail under sustained frame pressure |
| `move_icons` | `false` | let them physically drag your icons |
| `move_windows` | `false` | let them nudge your windows a few pixels; *Put my windows back* undoes it |
| `shots_over_icons` | `true` | stray fire passes over icons; aimed fire and blasts still land |
| `blood` | `false` | cartoon blood: sprays on hits, stains the floor, fades; water balloons mop it |
| `react_to_windows` | `true` | comment on window titles, follow focus |
| `sleep_when_idle` | `true` | |
| `idle_minutes` | `5.0` | |
| `all_monitors` | `true` | off keeps them on the primary screen |
| `pause_fullscreen` | `true` | hide while a fullscreen app is in front: a game, a film, a slideshow |
| `start_with_windows` | `false` | adds a `Run` key entry |

The rendering rate is what you set while you are watching. Asleep, they draw
at up to 10 a second; on battery, at up to 20; hidden behind a fullscreen app,
the environment is checked four times a second. Simulation uses fixed 60 Hz
steps independently of rendering. Pause and fullscreen holds freeze it;
long stalls discard excess backlog instead of producing a burst of old actions.

**Tray → Performance** shows the active renderer, actual FPS, simulation and
drawing cost, particle count, current detail, and discarded simulation time.
Automatic quality changes only decoration. Disable it to keep your chosen
detail level. Settings are grouped into Look, Performance, Behaviour, Cast, and Your desktop.

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
- **Fullscreen apps** hide them. A game, a film, a slideshow: anything whose
  window covers a whole monitor, taskbar included, and has the focus. The
  overlay is withdrawn while it is in front — not just left transparent, since
  a topmost window over a borderless game is still composited every frame —
  and comes back when it goes. `pause_fullscreen` turns that off.
- Multi-monitor works; turn it off to keep them on the primary screen. Dock,
  undock or change resolution and the overlay re-covers the desktop by itself.
- **One at a time.** A second launch says so and exits; the tray icon of the
  first one is where Quit lives.

---

## How it works

A single always-on-top `tkinter` window covers the virtual screen. Its layered
window uses `#010101` as a transparency colour, including input transparency in
empty space. The native visual/input windows are disabled: their transparent
graphics did not provide reliable input transparency to other applications.
See [the incident report](INCIDENT_INPUT_LOCKOUT.md) for the cause and corrected
test coverage. The normal application has no path to construct a native overlay.

The figures are drawn procedurally, not from sprites: a skeleton with two-bone
IK for authored actions and four constrained passive limbs during grabs,
throws and knockouts, then squashed and mirrored. That's
why they scale cleanly from icon-sized to huge, and why adding a weapon is a
dozen lines rather than a spritesheet.

Short eased transitions connect upper-body poses while planted feet and ledge
grips stay exact. Weapons have distinct windups, recoil, and impact effects;
projectiles use the same posed muzzle that gets drawn.

Fighters use one-way platforms, swept body contacts at window edges and a
ledge-grab pass. Climbable surfaces overhead can be scaled hand-over-hand and
mantled. Impulses account for body mass, while surfaces control friction and
bounce. Motion speeds and gravity scale with body size.

The ragdoll controls four limbs around the existing authored root; it does not
replace the fighter with a full rigid-body skeleton. Crates move and rotate,
with conservative box contacts for terrain and stacks. Their projectile
contacts use the polygon that is drawn. Seesaws rotate around an anchored
pivot; ramps, fans and conveyors stay anchored. See [the physics guide](PHYSICS_GUIDE.md).

## If something goes wrong

The EXE and `.bat` launch without a console. Diagnostics go to
**`gremlin_log.txt`** in `%LOCALAPPDATA%\DesktopGremlin` for the EXE, or beside
the script for source runs. The tray icon pops a balloon once to say so. That file is
the first place to look, and the right thing to attach to an issue. Its first
banner names the version and the commit when available, so a fix
that "didn't work" can be checked against the code that actually ran.

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

50 checks on Windows; the Linux runner selects shared and Linux checks.
Linux acceptance requires an isolated Xvfb session as documented in the Linux
build guide. Frozen Linux acceptance also proves real input delivery and exit
using a separate receiver process.
They drive the real app
with the Windows shell stubbed out, so they never touch your desktop. Every one
of them checks a concrete behavior or regression. The same checks run on every push
in GitHub Actions, on a Windows runner.

---

## License

MIT — see [LICENSE](LICENSE).
