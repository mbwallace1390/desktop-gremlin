# Desktop Gremlin 3.0.0 delivery

The four approved feature updates are implemented. The Windows distribution
bundles its runtime so end users install no Python or packages.

| Update | Delivered |
|---|---|
| Arsenal | Boomerang, bubble, freeze, swap, glove, rubber and foam; shared timed effects and shields |
| Movement | Pendulum ropes, wall kicks, rolls, vaults, dodge slides, paper planes and team boosts; five interactive toy types |
| Social | Saved friendships/rivalries, strongest-target alliances, betrayal, rescues, hat heists, false surrender, spectators, court, quiet activities and window inspectors |
| Controls | Arbitrary cast selection, nicknames, halo colors, hats, strict weapon choices, Peaceful/Mischief/Battle modes and independent activity switches |

The complete controls and behaviors are in [EXPANSION_GUIDE.md](EXPANSION_GUIDE.md).
The [preview](docs/expansion-preview.svg) contains 221 actual Canvas items exported
from three controlled app frames, with fake terrain and a withdrawn Tk window.

## Validation

- `./.venv/Scripts/python.exe -B tests/run_all.py`: **37/37 suites pass**.
- All nine runtime modules parse with Python 3.8 syntax.
- Mixed simulation: six simulated minutes across 1, 4 and 10 characters,
  scales 0.35, 0.68 and 2.5, and all three modes. Ownership, bounded object counts,
  finite physics and cleanup remain valid.
- Independent reviews and regression tests covered collision ordering,
  same-frame projectile cancellation, rescue ownership, alliance targeting,
  rope grip transitions, separate toy controls, mode changes during flight,
  and corrupt saved relationship values.
- The five existing user settings/memory/backup/log/icon files retain their
  pre-expansion SHA-256 hashes. Tests use isolated files and fake desktop I/O.
- Native presentation remains disabled. Normal startup is Tk. Keyboard-exit
  dispatch and hidden-window cleanup are tested without injecting desktop input.

## Windows download

The release ZIP contains `DesktopGremlin.exe`, its `_internal` runtime folder,
licenses and `README-FIRST.txt`. It excludes personal settings, counters, icon
labels/backups and logs. Writable state lives in `%LOCALAPPDATA%\DesktopGremlin`.

Build and release verification are described in
[packaging/BUILDING.md](packaging/BUILDING.md). The packaged diagnostic runs
from a separate working directory with installed Python removed from PATH,
and verifies that imports come from the bundle, Tk draws, every expansion
engine runs, settings/memory round-trip, the instance guard works, and the
queued emergency exit cleans up.

End-user flow: **GitHub Releases → Windows ZIP → Extract All → DesktopGremlin.exe**.
See [USER_DOWNLOAD_GUIDE.md](USER_DOWNLOAD_GUIDE.md) for updates, migration and removal.

The workflow prepares a draft release on a matching version tag. No commit,
push, tag or public release was made during this work. A clean separate PC's
visual/input acceptance and the public GitHub download are separate from the
local automated evidence above.
