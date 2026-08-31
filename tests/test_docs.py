"""Do the docs still describe the code?

Not prose review -- just the claims that are checkable, and that go stale
silently because nothing breaks when they do: the settings table, the files it
writes, the tray menu, the weapon list, the size of the cast, and how many
checks there are. Every one of these has been wrong at some point.
"""
import importlib.util
import io
import os
import re
import sys

_TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_TESTS)
SRC = os.environ.get("GREMLIN_SRC", os.path.join(ROOT, "desktop_gremlin.py"))
HERE = os.path.join(_TESTS, ".tmp")
os.makedirs(HERE, exist_ok=True)

spec = importlib.util.spec_from_file_location("gm", SRC)
gm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gm)

readme = io.open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
# Prose wraps mid-phrase and writes "Show-off" for the character called
# "showoff". Matching raw text reports both as stale when they are just
# English, so searches run against a flattened, punctuation-stripped copy.
flat = " ".join(readme.split()).lower()
squashed = flat.replace("-", "").replace("'", "")
claude = io.open(os.path.join(ROOT, "CLAUDE.md"), encoding="utf-8").read()
app_src = io.open(SRC, encoding="utf-8").read()
bad = []

# --- the settings table must list exactly the real keys, with real defaults --
rows = dict(re.findall(r"^\| `([a-z_]+)` \| `([^`]+)` \|", readme, re.M))
missing = sorted(set(gm.DEFAULTS) - set(rows))
extra = sorted(set(rows) - set(gm.DEFAULTS))
if missing:
    bad.append("README settings table is missing: %s" % missing)
if extra:
    bad.append("README settings table lists keys that do not exist: %s" % extra)
for key, shown in rows.items():
    if key not in gm.DEFAULTS:
        continue
    real = gm.DEFAULTS[key]
    want = ("true" if real is True else "false" if real is False else str(real))
    if shown.strip().lower() != want.lower():
        bad.append("README says %s defaults to %s, code says %s"
                   % (key, shown, want))

# --- every file the code writes should be described ------------------------
for const in ("SETTINGS_PATH", "BACKUP_PATH", "MEMORY_PATH", "LOG_PATH"):
    name = os.path.basename(getattr(gm, const))
    if name not in readme:
        bad.append("README never mentions %s (%s)" % (name, const))

# --- the tray menu ---------------------------------------------------------
labels = re.findall(r'self\.tray\.add\("([^"]+)"', app_src)
for label in labels:
    stem = label.replace("...", "").strip()
    if " ".join(stem.split()).lower() not in flat:
        bad.append("README does not mention the tray item %r" % label)

# --- the weapons -----------------------------------------------------------
for w in gm.WEAPONS:
    shown = {"blaster": "blaster", "minigun": "minigun", "rocket": "rocket",
             "lightning": "lightning", "sword": "sword", "bow": "bow",
             "bomb": "bomb", "chainsaw": "chainsaw"}[w]
    if shown not in flat:
        bad.append("README does not mention the %s" % w)

# --- the cast --------------------------------------------------------------
for name in gm.ROSTER:
    if name.lower() not in squashed:
        bad.append("README does not name %s" % name)
if "1 to 10" not in readme and "one to ten" not in readme.lower():
    bad.append("README does not say how many of them there can be")

# --- how many checks there are ---------------------------------------------
count = len([f for f in os.listdir(_TESTS)
             if f.startswith("test_") and f.endswith(".py")])
words = {10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen",
         14: "fourteen", 15: "fifteen"}
word = words.get(count, str(count))
for doc, text in (("README.md", readme), ("CLAUDE.md", claude)):
    claimed = re.search(r"\b(ten|eleven|twelve|thirteen|fourteen|fifteen)"
                        r" checks\b", text, re.I)
    if not claimed:
        bad.append("%s does not say how many checks there are" % doc)
    elif claimed.group(1).lower() != word:
        bad.append("%s says %s checks, there are %d"
                   % (doc, claimed.group(1), count))

# --- claims that the redesign made false -----------------------------------
for phrase, why in (
        ("The explosions are animation", "explosions move icons now"),
        ("Each has its own colour", "the figures are all black now"),
        ("`rival`", "the setting is crowd"),
        ("Set `rival:", "the setting is crowd")):
    if phrase in readme:
        bad.append("README still claims %r (%s)" % (phrase, why))

print("settings keys   : %d documented, %d real" % (len(rows), len(gm.DEFAULTS)))
print("files described : %d" % 4)
print("tray items      : %d" % len(labels))
print("cast named      : %d of %d" % (
    sum(1 for n in gm.ROSTER if n.lower() in squashed), len(gm.ROSTER)))
print("checks on disk  : %d (%s)" % (count, word))
print("")
if bad:
    print("STALE")
    for b in bad:
        print("  " + b)
    sys.exit(1)
print("PASS")
