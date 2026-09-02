# Desktop Gremlin

One to ten stick figures living on top of the real Windows desktop. One file,
`desktop_gremlin.py`, ~5400 lines, tkinter + pywin32, no other dependencies.
Windows only — it talks to the Explorer shell directly.

## Verify before believing it works

```
python tests\run_all.py
```

Sixteen checks, a few seconds, nothing to install. Each one encodes a bug that
actually shipped. They build a real Tk window and a real `App`, so windows
flash on screen while they run; none of them touch your desktop icons, because
the shell is stubbed out. `.github/workflows/checks.yml` runs the same command
on every push, on a Windows runner.

**Every check starts through `tests/harness.py`.** `harness.load(tag)` imports
the script and redirects all four files it persists to — settings, icon
backup, memory, log — into `tests/.tmp` before anything can write, then
`build()` makes the App and `fake_terrain()` serves a desktop. Do not open a
new check with a hand-rolled `importlib` preamble: the redirect is the part
that gets forgotten, and forgetting it writes a real settings file into the
repo (see below). `tests/test_runtime.py` is the model for a check that needs
the frame loop itself: it captures `root.after`, replays the ticks against a
fake clock, and drives the real `run()`.

**This is the mechanism, not a suggestion.** Every bug listed further down was
found by measurement and would have been missed by reading the code — several
were *invisible* to reading the code, because the maths was self-consistent and
simply described the wrong thing.

To prove a check still catches its bug, copy the script, put the bug back in
the copy, and point the check at it:

```
set GREMLIN_SRC=C:\path\to\broken_copy.py
python tests\run_all.py roaming
```

A check that passes against the broken copy is testing nothing.

## Verifying anything visual

Do not re-derive the pose maths in the test and check it against itself. Read
what was actually drawn — `canvas.coords()` on the pooled items gives you the
rendered joint positions, and `find_all()` in order gives you the true stacking.
`tests/test_gait.py` and `tests/test_joints.py` both work this way, and both
found bugs that had been shipped since v2.0.

**A green check can be a broken ruler.** The first version of the joint check
passed, confidently, and was wrong: it measured the perpendicular offset from
the chord and then guessed the sign from the limb's vertical direction.
Comparing the joint's x against the chord *at the joint's own height* has no
such ambiguity. If a report says something looks wrong and your check says it
is fine, suspect the check before suspecting the report.

**Drive the real entry point.** The first weapon-range check assembled a shot
by hand instead of going through `start_attack`, which is exactly where both
fixes lived, and so reported no change after a correct fix.

## Things that bite

**Module-level init runs top to bottom, and a catch-all eats the proof.**
`CFG = load_settings()` used to run two hundred lines above `ROSTER`; the
validation clamp's `len(ROSTER)` raised NameError into the clamp's own
`except`, which returns the defaults — so every saved settings file was
silently discarded on every launch, for a whole release, and the Settings
window read as amnesiac. Anything `load_settings` touches must be declared
above it. `tests/test_settings.py` holds the line by importing a sandbox copy,
because the bug only ever existed at import time.

**A test that drives the settings window writes a real settings file.**
`SettingsWindow.apply()` calls `save_settings(CFG)` and `set_run_at_startup()`,
so exercising it from a check drops a `gremlin_settings.json` into the repo
carrying whatever that check had forced — and the app then starts with those
values. This happened twice in one session, the second time after being caught
by the first. `harness.load()` now redirects `SETTINGS_PATH`, `BACKUP_PATH`,
`MEMORY_PATH` and `LOG_PATH` before a check can do anything else; that is the
mechanism, and the reason a check must start there. `set_run_at_startup()`
still writes a real Run key, so do not call `apply()` at all.

**The shell is read on a thread, and every primitive takes the lock.**
`Terrain.refresh()` only *asks* once `threaded` is set; `Scanner` does the
reading and `Terrain.poll()`, called every frame, takes the result in. The
scanner shares `SHELL` — and its one remote buffer in Explorer — with the frame
thread's icon writes, so `ShellView`'s primitives are `@_locked` per call: a
write landing between another call's write and its read would hand Explorer
the wrong struct. Per call and not per scan, so a carry waits for one message
and never for four hundred. `App.__init__` takes the one synchronous look, and
the checks stub `refresh` wholesale, which is why none of them see the thread.

**Our own overlay trips the shell's fullscreen flag.**
`SHQueryUserNotificationState` reports BUSY the moment a fullscreen window
appears, ours included — measured, not guessed — so `fullscreen_app()` judges
the *foreground* window's frame against its monitor instead. We are never
foreground (`WS_EX_NOACTIVATE`), a maximised window stops at the work area,
and the shell's own windows are skipped by class. Holding withdraws the
window: `withdraw()`/`deiconify()` keeps the HWND, the extended styles and
the transparent colour (also measured), and a topmost layered window merely
left transparent is still composited over a borderless game every frame.

**The loop is paced from a deadline.** `after(period)` at the end of a frame
adds the frame's own cost to every gap: 40 configured ran at 31.7 with ten on
screen, and 39.9 after. `frame_period()` is also where asleep, battery and
held slow the tick; the `dt` cap follows it, or a 100 ms tick would run the
simulation at half speed.

**The icon backup is re-taken every launch, unless the last run left icons
moved.** `set_item_pos` flags the file (`dirty`) on the first real move of a
run, `restore_layout` clears it, and `backup_layout` keeps the old snapshot
while the flag stands — that copy is the only good one. A restore's own writes
go through `_restoring` so they do not re-flag it. `first` and `previous` in
the file are for hand recovery and on no menu.

**Two coordinate systems.** `item_rect` returns screen pixels, `item_pos` and
`SETITEMPOSITION32` want listview coordinates. They differ by a constant for
the whole view, so one probe read gets the offset and everything else is a
write — see `blast_icons`.

**Nothing moves an icon unless `move_icons` is on**, and it is off by default
and force-disabled when there is no `gremlin_icon_backup.json` to undo with.
A whole round trip was spent on "the bombs aren't clearing icons" when the
setting had never been switched on. Check `CFG["move_icons"]` and `BACKUP_OK`
before diagnosing anything about icons not moving.

**Every `LVM_*` call goes through `send_msg`,** never `SendMessage`. A plain
cross-process SendMessage blocks until Explorer answers; with 400 icons that is
~800 blocking IPC calls every 1.6s, and a busy Explorer froze the whole thing.
The timeout bounds each call; the scanner thread is what keeps the sum off
the frame. Measured on this machine: 0.04 ms an icon warm, so 400 is 16 ms.

**`update_fighter` is a dispatch table.** `STATES` maps a state name to its
`_st_*` method; each gets `(f, dt, K)` and returns True to end the update
early, which is what a joyride does because `start_ride` has already moved
him. Adding a state is one method and one table entry. The split was proved
mechanical by hashing a deterministic two-and-a-half-minute ten-way brawl
before and after: identical.

**Under `pythonw` there is no console.** `sys.stdout` and `sys.stderr` are
`None`, `print()` silently does nothing, and Tk's default handler for
exceptions inside callbacks writes into the void — so a failure leaves no trace
anywhere and they just stop doing whatever it was. `start_log()` redirects both
streams to `gremlin_log.txt` when there is no console. Look there first.

**Tray menu callbacks must not touch Tk.** A click arrives as `WM_COMMAND`
dispatched inside `TrackPopupMenu`'s own modal message loop, which is inside
`PumpWaitingMessages`, which is inside the Tk frame callback. Building a window
or destroying the root from there re-enters the interpreter three deep.
`Tray._on_command` queues; `Tray.drain()` runs them from the frame loop.

**Two different scale factors, and they are not interchangeable.**
`K = sc / 1.75` scales speeds, forces and gravity. `(.4 + .6 * K)` scales the
distances the AI opens fire from. At the default scale that is 0.39 against
0.63, so a weapon tuned by one and aimed by the other falls short — which is
what made arrows land 100px in front of the target.

**The body is `BODY`, and mood is the halo.** `Fighter.body()` is the black
every figure is drawn in; `Fighter.color()` is the mood colour, and it now only
reaches the halo, the speech bubble and the grab rings. The halo is free because
a Tk oval carries a fill AND an outline in the same canvas item — outlining the
limbs the same way needs a second line under each one, measured at ten of them
as +168 items and +25% of the frame. `FACE` is light because it is drawn on top
of the black head; it used to be near-black on a coloured one, which is why the
per-mood expressions were invisible.

**A round has to outrun the distance it is fired from, and gravity is usually
what stops it.** The fight state walks him to `REACH[weapon]` scaled; a round
that only just covers that falls short the moment either of them moves, which
is most of the time. Both the minigun and the rocket shipped stopped by the
FLOOR rather than by their own lifetime — aimed three degrees down at the other
one's chest from a muzzle 39px up, they buried themselves at 498px and 353px
with most of their life left. Raising the lifetime, the obvious move, did
nothing for either; cutting gravity did. `tests/test_weapon_range.py` holds the
line at 1.5x, and judges lobs (bow, bomb) on whether they land instead, because
a good lob is 1.0x by construction.

**Every new drawing call has to pick a layer.** Canvas items are pooled and
reused rather than recreated, and Tk draws in creation order, so stacking comes
from `_frame_end()` raising the layer tags in a fixed sequence. A `self.line()`
with no preceding `self.layer(...)` inherits whatever layer ran last.

**The canvas is the bottleneck, and it is paint, not item churn.** Measured:
2.0 ms/frame of a 25 ms budget, ~80% of it painting a fullscreen layered
window. Pooling items instead of recreating them was worth 1.14x. More
particles and more fighters are the two things you cannot buy.

## Design decisions worth not relitigating

**Memory holds counters, never a log.** `gremlin_memory.json` keeps fight and
interaction counts plus the icon names they pick on most. Nothing about which
applications or windows you use is written to disk — the context in `Watcher`
lives in RAM and dies with the process. Settings has a "forget everything"
button. Keep it that way.

**The screen wraps sideways.** Off one edge and back on the other, keeping
height and speed. Two things send a fighter round: getting `WRAP` past the edge,
or being out of sight for `OUT_MAX` at all. The second one matters more than it
looks -- without it a duel settles a few pixels past the edge, never travels far
enough to trigger, and carries on where you cannot see it. He lands just INSIDE
the far edge, because landing outside lets an idle fighter wrap, sit out of
sight, and wrap again forever. There is no wall any more, so `wallslide` is
currently an unreachable state. There used to be a hard ceiling 18px down, which
put the top row of desktop icons *above* it and trapped them there in a
grab-jump-bounce loop indefinitely; a ledge cooldown stops the re-grab.

**A weapon is its family, and the family is a tuple.** Beyond the plain guns:
`PULLERS` reel the victim in (the pull overrides hit_fighter's knockback,
applied after the call so the 3-arg spies in the checks keep working),
`DROPPERS` fall from the sky and only use REACH as walking distance, `TRAPS`
become entries in `app.traps` where they land and are sprung by `traps_tick`
(a peel thrown at a foe registers through `hit_fighter`, so a trap fight still
counts as a fight everywhere fights are counted), and `SOFT` weapons deal
moods, not wounds. The pan reflection happens inside the projectile
fighter-hit loop and hands the round to the reflector — `s["owner"] = f` —
so it can hit whoever fired it.

**Joyrides are states that skip physics, and every one must clean up.**
`RIDES` maps kind to transport menu; `start_ride` returns False when a
precondition is missing so `decide()` falls through. `end_ride` is the only
way out of the mount/rider/parachute/surf fields, and it is called from
grabbing, sleeping, the crowd slider and `hit_fighter` — a dangling `mount`
is the crowd-slider ghost bug wearing a new hat. Surfing rides a REAL icon
through the same `can_move_icons()` gate as dragging, and the balloon never
rises above `oy+120` because the roaming check counts `y < oy` as out of
sight. `tests/test_rides.py` holds all of it.

**The weapon he fires is the weapon he closed the distance for.** The fight
state walks him to `REACH[f.plan]`, so `start_attack` must use `f.plan` and
nothing else. It used to swap in a random other weapon half the time, which
left him standing at lightning range swinging a sword: every chainsaw swing and
9 in 10 sword swings were thrown from outside their own reach, and only
lightning appeared to work -- it is instant, and was only ever fired when it was
also the plan. Variety comes from re-rolling `f.plan` *between* attacks, where
the fight state still gets a chance to close the new distance.

**Shots meant for the other fighter pass over the desktop.** `f.at_foe` is set
in `start_attack` and becomes `pierce` on the projectile. Without it a row of
icons between them soaks up every round. Under `shots_over_icons` (default on)
cursor fire and aimed fire pierce too — but an aimed round must carry its
target as `tgt`, the one thing it may still hit, or the pierce carries it
through the very window it was fired at. Shots aimed *at* an icon still hit it,
and blast radius still catches icons either way. The wall in
`tests/test_weapon_range.py` used to stand at x=700 while every duel happened
by x=554 — a green column that intercepted nothing — so move the wall, not the
fighters, when the geometry changes.

**Adding a line they can say is one table edit.** `VOICES[kind][event]`, and
`f.yell("event")` at the site. All ten must carry the same 34 event keys, and
no two may share a line — `tests/test_voices.py` fails on either, and a missing
key is a `KeyError` in the middle of a fight.

**The cast is data, and `ROSTER` is the order they join in.** The halo colour
comes from `BASECOL` through `palette()`, which derives the six mood shades
rather than hand-picking sixty. Each character keeps its own base, so the halo
carries identity *and* mood at once — that is why making the bodies black cost
nothing in telling them apart. Temperament is `TRAITS`: `aggro`, `chatty`, `grudge`,
`dash`, `hops`, `thief`, `nerve`. Every one is wired to arithmetic that already
existed except `nerve`, the health he breaks off a fight at.

**`chatty` has to gate something people notice.** It first only gated remarks
about your windows, and a fivefold spread in the trait produced barely a
doubling in how much they actually said. It now also gates mood lines, which is
what makes the Grump quiet and the Drama exhausting.

**Memory is keyed by `ROSTER` under `MEM["who"]`,** not by fighter names sitting
at the top level beside `version` / `runs` / `icons`. Anything that changes the
roster orphans the old counters; `load_memory` drops what it does not recognise.

**A remark nobody was free to say has to be handed back.** `Watcher.pick()`
marks it said and goes quiet for two minutes the moment it returns one, so
dropping it because every fighter was mid-swing bought two minutes of silence
for nothing — and with ten of them brawling, that was most of them. Call
`unsay()`.

**Ten of them cost about 6 ms of a 25 ms budget**, about 400 canvas items. The
count is not the thing to worry about; paint is. That budget is the default
40 fps; a settings file at 60 has 16.7 ms, and the same ten are 37% of it.

**One instance, by mutex.** `claim_instance()` in `main()`, before anything is
written. The handle is held for the life of the process and never closed;
Windows drops it on exit, crash included.
