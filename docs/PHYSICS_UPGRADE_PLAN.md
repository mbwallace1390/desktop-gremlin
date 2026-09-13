# Physics upgrade

Approved scope: all eight ideas from the September 13 physics review.

Implement shared contact normals/materials and additive directional impulses;
radial blast falloff; swept character contacts; spring grabbing with recent
mouse history; joint-limited ragdoll limbs and recovery; dynamic crates and
weight-driven seesaws, fans and conveyors; moving-window ropes; selectable
surface materials and cartoon physics presets.

Keep the 60 Hz simulation, bounded crowds/props/projectiles, Tk rendering,
native renderer quarantine, existing desktop permissions and portable builds.
No new runtime packages. Desktop windows remain user-controlled surfaces.

Work is split by module: root owns main simulation/shared helpers/settings;
separate workers own motion props/ropes, arsenal contacts, and ragdoll limbs.
Shared APIs are segment_contact/reflect/material/preset, impact_fighter,
MotionEngine.projectile_contact/hit_prop/blast/surface_velocity, and Ragdoll
update/pose/joints. Main integration follows the module implementations.

Verification: failing focused physics regressions before implementation;
existing full harness suite; mixed ten-gremlin simulation across presets and
sizes; rendered joint measurements; public bundle build and isolated frozen
startup checks. Tests must redirect all five persisted files through harness.

Implementation complete. Local verification: 46/46 harness suites passed;
standalone Windows build passed all ten frozen checks with Python removed from
PATH. Personal settings, memory, icon backup, log and tray-icon hashes matched
their pre-test values. GitHub Actions repeats the source and packaged gates on
Windows and Linux before preparing the public release downloads.

Review fixes included platform edge movement, sweep reset after screen wrapping,
negative blast attraction for props, support removal waking crate stacks, and
bundled-origin validation for both new physics modules. PHYSICS_GUIDE.md records
the controls, visible behavior and deliberate cartoon-physics approximations.
