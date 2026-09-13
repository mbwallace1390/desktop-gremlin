# Desktop Gremlin 2.1.1 — corrected upgrade handoff

**The native renderer shipped in 2.1 caused a desktop input lockout. It is now disabled. The earlier claim that cross-process click-through was verified was wrong: the test checked window lookup, not actual input delivery.**

See [INCIDENT_INPUT_LOCKOUT.md](INCIDENT_INPUT_LOCKOUT.md) for the cause, containment and requirements before native presentation can be reconsidered.

## Current behavior

- Normal startup and Settings use the original Tk canvas. Missing, invalid or older `renderer: auto` settings cannot enable native windows.
- Native construction is blocked in `gremlin_renderer.py`, including from old test/preview scripts. There is no user-facing native renderer option.
- Ctrl+Alt+Shift+Q requests an exit without mouse access. It is registered as a Windows hotkey independently of the notification icon; registration failure is reported. Quit hides the overlay before cleanup and still destroys the root if another cleanup operation raises.
- Eased pose transitions, aligned weapon muzzles, improved combat feedback, dark/light bodies, halo strength and optional outlines remain available.
- Fixed 60 Hz simulation, bounded catch-up, batched desktop writes, occupied window tracking, platform navigation and failed-edge cooldowns remain.
- Adaptive decorative effects, separate effects randomness, tabbed Settings and the live performance panel remain.
- Ordinary projectiles now fly until impact or leaving the desktop, instead of disappearing when a short cleanup timer expires. Thrown items reach their actual landing point; bombs and black holes retain their intentional fuses. Leaving the screen no longer triggers a false explosion or places a trap on the floor.

`desktop_gremlin.py` and `gremlin_performance.py` are the active application modules. Native code is retained only for diagnosis and must remain quarantined. `docs/upgrades.png` is a historical native preview, not the current renderer.

## Verification

Run `python tests/run_all.py` for all 30 suites. Recovery checks cover production defaults, old settings, native-constructor tripwires, the real Tk startup path, Settings choices, hotkey dispatch/cleanup, and failure-safe quit. The harness no longer overrides the renderer with a different default. Projectile flight checks cover small gremlins and wide desktops, drawn shots and late hits, physical landings, fuses, and cleanup; they also fail against the source from before the flight fix.

The [September 12 audit](AUDIT_2026-09-12.md) also repairs icon backup coverage,
retryable window restores, failed cursor samples, drag state during hiding,
landing order, delayed-shot ownership, long idle preferences, and cached icon
names after blasts. Native presentation remains disabled.

Native graphics benchmarks and the previous composed-pixel probe do not prove safe input delivery and must not be cited as such. Old native probe/preview entry points now refuse to run.

The audit fixes remain documented in `AUDIT_FINDINGS.md`.
