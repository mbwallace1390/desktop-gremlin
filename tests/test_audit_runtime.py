"""Runtime audit regressions, with the machine boundary stubbed by the harness.

Slow scans use Events; tray recreation, frame scheduling and duplicate launch
use fakes. Monitor tests drive the actual physics with the actual Fighter.
"""
import contextlib
import io
import os
import sys
import threading
import time
import types
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness

gm = harness.load("audit_runtime")
bad = []


def check(name, condition):
    print("%-48s %s" % (name, "PASS" if condition else "FAIL"))
    if not condition:
        bad.append(name)


# Polling must return while Explorer is deliberately blocked, and a newer
# request made during that scan must still run after it finishes.
entered, release, polled, next_scan = [threading.Event() for _ in range(4)]
calls = []


def blocked_scan(hwnd, icons):
    calls.append((hwnd, icons))
    if len(calls) == 1:
        entered.set()
        release.wait(2)
    else:
        next_scan.set()
    return ([hwnd], [])


with patch.object(gm, "scan_desktop", blocked_scan):
    scanner = gm.Scanner()
    scanner.request(101, True)
    started = entered.wait(1)
    poller = threading.Thread(target=lambda: (scanner.take(), polled.set()), daemon=True)
    poller.start()
    responsive = polled.wait(.15)
    scanner.request(202, False)
    release.set()
    finished = next_scan.wait(1)
    poller.join(1)
    deadline = time.perf_counter() + 1
    result = None
    while time.perf_counter() < deadline and result != ([202], []):
        result = scanner.take()
        if result != ([202], []):
            time.sleep(.001)
check("scan polling remains responsive", started and responsive)
check("new request survives an in-flight scan",
      finished and calls == [(101, True), (202, False)] and result == ([202], []))


# Simulate Windows delivering the registered TaskbarCreated message. No actual
# Explorer restart, tray window, or Shell_NotifyIcon call is involved.
gui = gm.win32gui
handlers, notifications = {}, []


def register_class(wc):
    handlers.update(wc.lpfnWndProc)
    return 1


fake_gui = types.SimpleNamespace(
    RegisterWindowMessage=lambda name: 0xC123,
    WNDCLASS=lambda: types.SimpleNamespace(), RegisterClass=register_class,
    CreateWindow=lambda *args: 1001, UpdateWindow=lambda *args: None,
    LoadImage=lambda *args: 1002, LoadIcon=lambda *args: 1003,
    Shell_NotifyIcon=lambda op, data: notifications.append((op, data)),
    NIF_ICON=gui.NIF_ICON, NIF_MESSAGE=gui.NIF_MESSAGE, NIF_TIP=gui.NIF_TIP,
    NIM_ADD=gui.NIM_ADD, NIM_DELETE=gui.NIM_DELETE,
)
with patch.object(gm, "win32gui", fake_gui), patch.object(gm, "_write_ico", lambda path: path):
    tray = gm.Tray()
    action = lambda: None
    tray.add("Example", action)
    built = tray.build()
    restart = handlers.get(0xC123)
    if restart is not None:
        restart(tray.hwnd, 0xC123, 0, 0)
    check("taskbar restart re-adds the existing icon",
          built and restart is not None and len(notifications) == 2
          and all(op == gui.NIM_ADD for op, data in notifications)
          and notifications[0][1] == notifications[1][1]
          and tray.items[0][1] is action and tray.added)


# Exercise the real startup entry point with a refused mutex. The real logger
# would truncate this sandboxed file if it ran before the mutex decision.
with open(gm.LOG_PATH, "w", encoding="utf-8") as file:
    file.write("active instance diagnostics\n")
original_out, original_err = sys.stdout, sys.stderr
try:
    with patch.object(gm, "claim_instance", lambda: False), \
            patch.object(gm, "fatal", lambda *args, **kwargs: None):
        sys.stderr = None
        gm.main()
finally:
    diverted = sys.stderr
    sys.stdout, sys.stderr = original_out, original_err
    if diverted is not None and diverted is not original_err:
        diverted.close()
with open(gm.LOG_PATH, encoding="utf-8") as file:
    check("duplicate launch preserves active log",
          file.read() == "active instance diagnostics\n")


def bare_app(monitors):
    app = gm.App.__new__(gm.App)
    from gremlin_arsenal import Arsenal
    from gremlin_motion import MotionEngine
    from gremlin_social import SocialDirector
    app.fighters, app.shots = [], []
    app.arsenal = Arsenal(app, gm.CFG)
    app.motion = MotionEngine(app, gm.CFG)
    app.social = SocialDirector(app, gm.CFG, lambda: gm.MEM, gm.mark_memory_dirty)
    app.mons = monitors
    app.ox = min(mon[0] for mon, work in monitors)
    app.oy = min(mon[1] for mon, work in monitors)
    app.W = max(mon[2] for mon, work in monitors) - app.ox
    app.H = max(mon[3] for mon, work in monitors) - app.oy
    app.terrain = types.SimpleNamespace(platforms=[])
    app.time = 0
    app.asleep = False
    app.mouse = {"x": -9999}
    app.puff = lambda *args: None
    app.shake = lambda *args: None
    return app


def falling_fighter(x, y, vx=0):
    fighter = gm.Fighter(x, y)
    fighter.set_state("fall")
    fighter.vx, fighter.vy = vx, 0
    fighter.on_ground = False
    return fighter


def advance(app, fighter, seconds):
    for tick in range(round(seconds * 40)):
        app.physics(fighter, .025, app.ground_at(fighter.x, fighter.y))
        app.time += .025


upper = ((0, 0, 1920, 1080), (0, 0, 1920, 1040))
lower = ((0, 1080, 1920, 2160), (0, 1080, 1920, 2120))
stacked = bare_app([upper, lower])
lower_f = falling_fighter(900, 1500)
selected_floors = []
with patch.object(stacked, "physics", lambda f, dt, gy: selected_floors.append(gy)):
    stacked.update_fighter(lower_f, .025)
check("fighter update uses its vertical monitor position", selected_floors == [2120])
advance(stacked, lower_f, 3)
check("lower stacked display retains its floor", lower_f.y == 2120 and lower_f.on_ground)
upper_f = falling_fighter(900, 900)
upper_f.vy = 9000
advance(stacked, upper_f, .025)
check("fast fall lands on upper display first", upper_f.y == 1040 and upper_f.on_ground)

short = ((0, 0, 1000, 800), (0, 0, 1000, 760))
tall = ((1000, 0, 2000, 1200), (1000, 0, 2000, 1160))
uneven = bare_app([short, tall])
crossing = falling_fighter(1001, 1160, -200)
crossing.on_ground = True
advance(uneven, crossing, .025)
check("shorter monitor floor applies on seam crossing",
      crossing.x < 1000 and crossing.y == 760 and crossing.on_ground)
wrapping = falling_fighter(2000 + gm.WRAP + 1, 1160)
advance(uneven, wrapping, .025)
check("side wrap lands on destination display floor",
      wrapping.x == 24 and wrapping.y == 760 and wrapping.on_ground)

gapped = bare_app([short, ((1400, 0, 2400, 800), (1400, 0, 2400, 760))])
check("gap recovery selects nearest real monitor",
      gapped.monitor_at(1350, 400) == gapped.mons[1])
hidden = falling_fighter(1200, 760)
advance(gapped, hidden, gm.OUT_MAX + .2)
check("empty gap cannot retain an invisible fighter",
      any(mon[0] <= hidden.x < mon[2] and mon[1] <= hidden.y <= work[3]
          for mon, work in gapped.mons))

left = ((-1000, 0, 0, 800), (-1000, 0, 0, 760))
with patch.object(gm, "monitors", lambda: [left, short]), \
        patch.object(gm, "virtual_screen", lambda: (-1000, 0, 2000, 800)):
    box, selected = uneven.screen_box()
check("single-display mode selects actual primary", box == (0, 0, 1000, 800) and selected == [short])

# Monitor removal must also handle negative Y, rather than only clipping X and
# the floor. A fake root records geometry without moving any real window.
refit = bare_app([((0, -1080, 1920, 0), (0, -1080, 1920, -40)), upper])
refit.fighters = [falling_fighter(900, -500)]
refit.root = types.SimpleNamespace(geometry=lambda value: None)
refit.canvas = types.SimpleNamespace(config=lambda **kwargs: None)
refit.screen_box = lambda: ((0, 0, 1920, 1080), [upper])
changed = refit.fit_screen()
check("undocking upper monitor brings fighter into view",
      changed and 0 <= refit.fighters[0].y <= 1040)


# Drive the actual run() callback: persistent errors should retain one full
# traceback, keep scheduling frames, and stop filling the log after 20 errors.
scheduled = []
loop = gm.App.__new__(gm.App)
loop.root = types.SimpleNamespace(after=lambda ms, fn: scheduled.append(fn), mainloop=lambda: None)
loop.tray = types.SimpleNamespace(pump=lambda: None, drain=lambda: None)
loop.running, loop.held, loop.paused = True, False, False
loop.env_at = time.perf_counter()
loop.check_environment = lambda: None
loop.frame_period = lambda: .025
loop.poll_cursor = lambda dt: None
loop._frame_errs = 0
loop.draw = lambda: None
loop.record_performance = lambda *args: None


def failed_update(dt):
    raise ValueError("audit frame failure")


loop.update = failed_update
capture = io.StringIO()
clock = types.SimpleNamespace(now=100.0)
loop.env_at = clock.now
with patch.object(gm, "DEBUG", False), \
        patch.object(gm, "time", types.SimpleNamespace(perf_counter=lambda: clock.now)), \
        contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture):
    loop.run()
    for index in range(25):
        clock.now += .025
        scheduled.pop(0)()
output = capture.getvalue()
check("first frame failure retains traceback without flooding",
      output.count("Traceback (most recent call last)") == 1
      and "failed_update" in output and output.count("frame error:") == 20
      and len(scheduled) == 1 and loop._frame_errs == 20)

print("\n" + ("FAIL\n  " + "\n  ".join(bad) if bad else "PASS"))
harness.finish(gm, None, bad)
