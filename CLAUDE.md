# Desktop Gremlin

Two stick figures living on top of the real Windows desktop. One file,
`desktop_gremlin.py`, ~3000 lines, tkinter + pywin32, no other dependencies.
Windows only — it talks to the Explorer shell directly.

## Verify before believing it works

```
python tests\run_all.py
```

Ten checks, about two seconds, nothing to install. Each one encodes a bug that
actually shipped. They build a real Tk window and a real `App`, so windows
flash on screen while they run; none of them touch your desktop icons, because
the shell is stubbed out.

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
~800 blocking IPC calls every 1.6s on the frame loop thread, and a busy
Explorer froze the whole thing.

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
icons between them soaks up every round. Shots aimed *at* an icon still hit it,
and blast radius still catches icons either way.

**Adding a line they can say is one table edit.** `VOICES[kind][event]`, and
`f.yell("event")` at the site. Both characters must carry the same event keys —
`tests/test_voices.py` fails if they drift, and a missing key is a `KeyError`
in the middle of a fight.
