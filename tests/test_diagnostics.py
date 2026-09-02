"""The crash instrumentation, without needing a detached process.

1. start_log() only kicks in when there is no stderr, and captures prints.
2. A Tk callback error reaches that log instead of vanishing.
3. Tray menu actions are queued, not run inside the Win32 window procedure.
4. Quit from the tray does not leave the frame loop touching a dead root.
"""
import os
import sys

import win32con
import win32gui

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

bad = []
gm = harness.load("diag")
LOG = gm.LOG_PATH

# --- 1. with a console, it must stay out of the way -------------------------
if os.path.exists(LOG):
    os.remove(LOG)
gm.start_log()
print("console present, log written: %s" % os.path.exists(LOG))
if os.path.exists(LOG):
    bad.append("start_log wrote a file even though there is a console")

# --- ...and without one, it must take over ----------------------------------
real_out, real_err = sys.stdout, sys.stderr
sys.stderr = None
handle = gm.start_log()
took_over = sys.stdout is not real_out
app = harness.build(gm)

# --- 2. a Tk callback error has to land in it -------------------------------
try:
    raise ValueError("a callback blew up")
except ValueError:
    app.on_callback_error(*sys.exc_info())

# --- 3. tray actions are queued, not run in the window procedure ------------
idx = [it[0] for it in app.tray.items].index("Settings...")
win32gui.PostMessage(app.tray.hwnd, win32con.WM_COMMAND,
                     app.tray.ID_BASE + idx, 0)
app.tray.pump()
queued = len(app.tray.pending)
opened_early = app.settings_win is not None
app.tray.drain()
opened_after = app.settings_win is not None

# --- 4. quitting from the tray must not leave the loop on a dead root -------
qidx = [it[0] for it in app.tray.items].index("Quit")
win32gui.PostMessage(app.tray.hwnd, win32con.WM_COMMAND,
                     app.tray.ID_BASE + qidx, 0)
app.tray.pump()
quit_queued = len(app.tray.pending) == 1
app.tray.drain()
stopped = not app.running

sys.stdout, sys.stderr = real_out, real_err
if handle:
    try:
        handle.close()
    except Exception:
        pass

log = open(LOG, encoding="utf-8").read() if os.path.exists(LOG) else ""
print("no console, log taken over  : %s" % took_over)
print("callback error in the log   : %s" % ("a callback blew up" in log))
print("log has a traceback         : %s" % ("Traceback" in log))
print("menu action queued not run  : %s (settings open during pump: %s)"
      % (queued == 1, opened_early))
print("drain then opened settings  : %s" % opened_after)
print("quit queued then honoured   : %s / %s" % (quit_queued, stopped))

if took_over is not True:
    bad.append("start_log did not take over when stderr was None")
if "a callback blew up" not in log or "Traceback" not in log:
    bad.append("a Tk callback error did not reach the log")
if queued != 1 or opened_early:
    bad.append("the menu action ran inside the window procedure")
if not opened_after:
    bad.append("draining did not open settings")
if not stopped:
    bad.append("quit from the tray did not stop the loop")

print("\n" + ("FAIL\n  " + "\n  ".join(bad) if bad else "PASS"))
harness.finish(gm, app, bad)
