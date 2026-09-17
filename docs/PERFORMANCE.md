# Performance fixes and verification

Measured on Windows, 2026-09-16, using Python 3.14.7. Baseline source:
`f691d10c0fd26239bac8ae7c0eec970513f237cd` (3.2.0).

## Repeatable frame measurements

The same benchmark drives the real `App.run()` callback in both source trees.
It uses controlled 40 Hz frame arrivals, the normal 60 Hz fixed simulation,
a 1920x1080 fake desktop, scale 0.68, seed 724, all expansion features enabled,
full visual quality, 480 warm-up frames, and 400 measured frames per repetition.
Results below are the median of three repetitions; times are milliseconds.
State counts, simulation step counts and peak projectile counts matched before
and after for every scene. This is a behavior consistency check, not a full
trajectory equivalence proof.

| Scene | Mean before | Mean after | p95 before | p95 after | Mean reduction |
|---|---:|---:|---:|---:|---:|
| Two gremlins, normal desktop | 0.397 | 0.410 | 0.661 | 0.695 | No meaningful improvement |
| Ten gremlins, five mixed toys | 2.306 | 1.827 | 3.230 | 2.491 | 21% |
| Ten gremlins, six crates | 3.877 | 1.923 | 5.474 | 2.626 | 50% |
| Ten gremlins, six crates, 400 icons | 7.346 | 3.949 | 10.765 | 5.602 | 46% |

The two-gremlin difference is 0.013 ms; no speedup is claimed there. The crate
and crowded-desktop reductions exceed variation across the repeated runs.
The default frame budget is 25 ms at 40 FPS.

These are CPU work measurements with Windows Tk withdrawn, using fake icons
and windows. Visible desktop painting/compositor load, GPU completion, real
Explorer responsiveness and other users' hardware are not established by them.
The new paint flush is included but does little work while the window is hidden.
The benchmark never changes real desktop icons or enables the quarantined native
renderer. Linux runs require an isolated Xvfb display, not the live desktop.

Reproduce from the repository root:

```powershell
.venv\Scripts\python.exe -B tests/benchmark_performance.py --repeats 3 --output build/performance-after.json
```

To compare a complete archived source tree, pass `--source-root PATH`; both the
entry script and its runtime modules load from that tree. Use the same benchmark
file, machine and settings, run the versions serially, and retain every repetition.
The local evidence from this run is in ignored `build/performance-audit/`.

## Changes

- Toy vertices, bounds and platform segments are reused until geometry changes.
  Sleeping crates avoid redundant support scans, with invalidation for moved or
  removed platforms, neighboring props, forces, floor height and physics settings.
- Projectiles use an ordered spatial index and direct lookup of explicit desktop
  targets. The existing exact swept collision tests still select the impact;
  lifetime, flight range and collision tie order are preserved.
- The Windows frame callback flushes Tk idle painting inside its drawing timer.
  The panel distinguishes p95 simulation/drawing work from p95 frame intervals.
  The latter includes scheduling and unmeasured work; GPU completion is not timed.
- Frame-thread Explorer calls share a small cumulative IPC allowance and avoid
  waiting behind the scanner lock. Current labels and uniqueness remain checked
  on every move, and durable undo protection is still required first.
- Recovery data is reused after validation instead of repeatedly parsing and
  scanning the complete JSON backup for every icon movement. Current file bytes
  and identity are checked even when timestamps are unchanged; a missing,
  unreadable or corrupted backup still blocks movement.

In a separate 400-icon recovery fixture with four historical snapshots, median
lookup cost fell from 0.769 to 0.123 ms (84%) across five 400-lookup repetitions.
An injected unresponsive Explorer call fell from about 250.26 to 4.62 ms across
three repetitions. These measurements use fake Explorer messages and isolated
files, not the user's desktop. Evidence is in `icon-io-results.json` alongside
the frame reports.

The shell allowance is not a hard real-time guarantee: durable file writes and
other OS calls can exceed it. An unavailable/busy Explorer yields a safe failure,
so an interrupted carry may be released rather than blocking the interface.

## Regression coverage

- `test_motion_performance.py`: reuse counts and stale-geometry/support cases.
- `test_collision_performance.py`: indexed versus exhaustive swept contacts,
  negative coordinates, radius, long sweeps, tie order and terrain changes.
- `test_icon_performance.py`: recovery cache invalidation, live identity checks,
  durable protection and scanner/IPC contention.
- `test_performance_upgrade.py`: real-loop paint timing and shell budget scope.
- `test_performance_budget.py`: full-feature mixed and crowded scenes through
  the real callback, reporting mean/p95 and guarding the 25 ms p95 CPU budget.

All are registered with `tests/run_all.py`; Windows-only shell checks are
excluded on Linux. Timing results are lab evidence, separate from visible
desktop acceptance and release-package verification.

Verification completed for these changes:

- Windows: 50/50 suites passed.
- Linux: 37/37 suites passed on isolated Xvfb with Openbox, including the
  cross-process desktop input check and the full-feature frame budget.
- All four changed runtime modules parse with Python 3.8 syntax rules.
- The sleeping-support regression fails against baseline source (60 redundant
  support scans instead of zero), and the real-loop paint test fails against
  baseline source (3 ms reported instead of the injected 10 ms drawing/paint).
- Native desktop presentation remains disabled. No live desktop icons were
  moved during these checks. These source measurements precede the 3.2.1 release;
  package build and download verification are separate release checks.
