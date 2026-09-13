"""Saved settings have to actually load on the next launch.

They didn't, for a whole release: load_settings() runs at import, its
validation clamp asked for len(ROSTER), and ROSTER was declared two hundred
lines further down. The NameError landed in the clamp's own catch-all, which
returns the defaults -- so every launch quietly threw the settings file away.
Nothing crashed, which is why nothing noticed.

Imports a copy of the real script from a sandbox with a settings file beside
it, because that is the real entry point: the bug only existed at import time,
and calling load_settings() on an already-imported module cannot see it.
"""
import importlib.util
import json
import os
import shutil
import sys

_TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_TESTS))
SRC = os.environ.get(
    "GREMLIN_SRC",
    os.path.join(os.path.dirname(_TESTS), "desktop_gremlin.py"))
HERE = os.path.join(_TESTS, ".tmp")          # scratch; never the repo itself
SANDBOX = os.path.join(HERE, "settings_sandbox")
bad = []

shutil.rmtree(SANDBOX, ignore_errors=True)
os.makedirs(SANDBOX)
COPY = os.path.join(SANDBOX, "desktop_gremlin.py")
shutil.copyfile(SRC, COPY)
SETTINGS = os.path.join(SANDBOX, "gremlin_settings.json")


def launch():
    """Import the sandbox copy fresh -- the same thing a real launch does."""
    spec = importlib.util.spec_from_file_location("gm_settings", COPY)
    gm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gm)
    return gm


def write(cfg):
    with open(SETTINGS, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)


# --- a saved file must survive the restart ---------------------------------
want = {"scale": 1.23, "fps": 24, "chaos": 2.2, "crowd": 7,
        "react_to_windows": False}
write(want)
gm = launch()
got = dict((k, gm.CFG[k]) for k in want)
print("saved and reloaded    : %s" % got)
if got != want:
    bad.append("saved settings did not survive the restart: got %s" % got)

# --- out-of-range values are clamped, not trusted --------------------------
write({"scale": 99, "fps": 1, "chaos": -4, "crowd": 999, "idle_minutes": 0})
gm = launch()
clamped = (gm.CFG["scale"], gm.CFG["fps"], gm.CFG["chaos"], gm.CFG["crowd"],
           gm.CFG["idle_minutes"])
print("hostile file clamped  : scale %s fps %s chaos %s crowd %s idle %s"
      % clamped)
if clamped != (2.5, 15, 0.2, len(gm.ROSTER), 0.5):
    bad.append("clamping wrong: %s" % (clamped,))

# --- junk falls back to the defaults ---------------------------------------
JUNK = ('not json', '[]', '{"scale": "big"}', '{"unknown_key": 1}')
for junk in JUNK:
    with open(SETTINGS, "w", encoding="utf-8") as fh:
        fh.write(junk)
    g2 = launch()
    if g2.CFG["fps"] != g2.DEFAULTS["fps"] or g2.CFG["crowd"] != g2.DEFAULTS["crowd"]:
        bad.append("junk %r changed the config: %s" % (junk, g2.CFG))
print("survived junk files   : %d variants" % len(JUNK))

# --- what the Settings window writes reads back ----------------------------
gm = launch()
gm.CFG["scale"] = 0.77
ok = gm.save_settings(gm.CFG)
back = json.load(open(SETTINGS, encoding="utf-8"))
print("write and read back   : saved=%s scale=%s" % (ok, back.get("scale")))
if not ok or back.get("scale") != 0.77:
    bad.append("save_settings round trip failed")

# --- the run counter must reach disk on a run where nothing else happens ----
gm = launch()
gm.MEM = gm.blank_memory()
gm.MEM_DIRTY = False
if not hasattr(gm, "count_run"):
    bad.append("count_run() is missing -- main() bumps runs without marking "
               "the memory dirty, so a quiet run is never counted")
else:
    gm.count_run()
    gm.save_memory()
    try:
        got_runs = json.load(open(gm.MEMORY_PATH, encoding="utf-8")).get("runs")
    except Exception:
        got_runs = None
    print("quiet run persisted   : runs=%s" % got_runs)
    if got_runs != 1:
        bad.append("a run with no interactions was never counted (runs=%r)"
                   % got_runs)

shutil.rmtree(SANDBOX, ignore_errors=True)
print("\n" + ("FAIL\n  " + "\n  ".join(bad) if bad else "PASS"))
sys.exit(1 if bad else 0)
