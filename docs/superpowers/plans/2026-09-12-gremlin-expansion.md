# Gremlin Expansion Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development. The user authorized the complete scope; keep executing without another approval gate.

**Goal:** Deliver every weapon, behavior, movement and customization feature in the approved proposal.

**Architecture:** Three independent engines extend the existing App through explicit update/control/draw hooks. Root integrates lifecycle, settings and persistence and checks the full feature matrix.

**Tech Stack:** Python 3.8-compatible syntax, existing Tk and pywin32.

**Spec:** `docs/superpowers/specs/2026-09-12-gremlin-expansion.md`

## Global Constraints

- Native renderer remains disabled; tests cannot manipulate the user's desktop.
- Preserve current uncommitted fixes and old settings/counters.
- No new runtime dependencies, background services, commits or pushes. Packaging adds pinned build tools only.
- All new engines use bounded objects and ordinary existing Tk drawing.

## Task 1: Arsenal and shared effects

Files: create `gremlin_arsenal.py`, `tests/test_expansion_arsenal.py`; modify combat tables, releases, poses, weapon drawing and damage-filter hooks in `desktop_gremlin.py`.

- [x] Tests first: real start_attack/release for all seven weapons; effect expiration/cancellation, shield absorption, bubble pop/rescue, frozen-slide collision, swap bounds, returning boomerang catch/bonk, rubber-ball bounce cap, foam release and glove recoil. Read pooled Canvas items for visible shots/effects.
- [x] Implement the exact Arsenal interface in the spec, including cleanup and ordinary input/state priorities.
- [x] Add each weapon to appropriate personality arsenals; honor profile-provided allowed lists.
- [x] Run new tests and range/muzzle/projectile_flight/input recovery gates; review this task's delta against `tests/.tmp/expansion_before/desktop_gremlin.py`.

## Task 2: Movement and toy props

Files: create `gremlin_motion.py`, `tests/test_expansion_motion.py`. Root edits App hooks/physics.

- [x] Write failing controlled simulations for rope momentum/release, paper-plane landing/crash, wall kick, roll, vault, dodge-slide and team boost.
- [x] Implement exact MotionEngine interface, with automatic consideration plus explicit start calls.
- [x] Test and implement all five prop kinds: crate support, seesaw impulse, ramp ascent, fan lift and conveyor transport. Cap count/lifetime and remove references on interruption/crowd changes.
- [x] Verify actual drawing and unrelated-state preservation; run motion and old rides/navigation/landing gates.

## Task 3: Relationships and scenes

Files: create `gremlin_social.py`, `tests/test_expansion_social.py`. Root integrates memory and App hooks.

- [x] Write tests exercising real scene updates and drawn props, not just registration lists.
- [x] Implement pairwise local-memory scores, rival selection helpers and breakable alliances; all data finite, bounded and keyed by roster identities.
- [x] Implement observable multi-stage rescue, hat-heist, surrender, spectators, court, cards, football, juggling, blanket-nap, coffee and resized-window inspector scenes with personality-specific lines/actions.
- [x] Validate interruptions/removal/hidden state, cooldown/caps, Peaceful mode, persistence reload and Forget.

## Task 4: Cast, controls and integrated release

Files: `gremlin_profiles.py`, `desktop_gremlin.py`, `tests/harness.py`, `tests/test_expansion_integration.py`, runner and docs.

- [x] Tests first for compatible settings, arbitrary cast identity preservation, profile validation, visible hats/colors/nicknames, loadout selection and all three modes.
- [x] Add configuration UI and engine lifecycle hooks. Engine control priority follows existing grab/KO/sleep transitions and never owns native input.
- [x] Include props in landing/navigation surfaces; hook social relationships into opponent choice/hits and inspectors into real terrain-change notifications.
- [x] Run a bounded mixed-feature simulation at multiple scales/crowds/FPS with default feature flags, plus whole suite and native quarantine checks.
- [x] Produce a visible safe preview, feature guide and completed checklist; independent whole-change review and final regression run.

## Task 5: Self-contained Windows distribution (user added)

- [x] After Tasks 1–4, build a Windows package containing the interpreter,
      Tk, pywin32 and every app module; end users install no Python or packages.
- [x] Include a clear launch entry point and keep writable settings/recovery
      data separate from bundled read-only internals.
- [x] Verify startup and runtime paths in the built package, quarantine and
      emergency exit, and archive contents on a clean dependency boundary.
- [x] Prepare GitHub release workflow/artifact names and an end-user download,
      extract and launch guide. Publishing is a distinct external action; the
      final deliverable must be concrete and reviewable before any approval.

## Progress ledger

- Planning complete. Source/runtime fingerprints saved in `tests/.tmp/expansion_before`.
- Ruling: use the authorized current checkout rather than create a worktree; it contains all prior repairs and .git is read-only. This preserves the user's complete working state.
- Ruling: scenes/props/traversal have their own module APIs; root alone owns the shared update and UI seams to prevent concurrent edits colliding.

- Tasks 1-3 implemented and independently reviewed. Targeted tests first reproduced absent features and later collision/cleanup integration regressions.
- Task 4 controls, persistence and lifecycle implemented. 37/37 suites passed in 22 seconds; the mixed test simulates six minutes across three sizes/crowds and all modes.
- Reviews fixed nearest freeze contact, reentrant projectile cleanup, rope entry grip, independent toy toggles, alliance targeting, rescued binding ownership, and delayed airborne combat intent after Peaceful mode.
- Packaging complete: the initial frozen test exposed missing Tcl scripts. Explicit packaged Tcl/Tk resources fixed it; nine frozen checks pass with installed Python removed from PATH. A second extracted copy passes with all payload files read-only and all payload hashes unchanged.

- Final delivery: `release/DesktopGremlin-3.0.0-Windows-x64.zip` (16,524,874 bytes); SHA-256 `3dced4a9c9cade6b420415c0cc8a737fcc62df3c6b310ac2dcc48af1d41fdc9a`.
- All nine frozen runtime modules match current source bytecode. Public publishing and separate-PC acceptance remain explicitly distinct from the completed local build.
- Final guides and preview: `DELIVERY_3.0.0.md`, `EXPANSION_GUIDE.md`, `USER_DOWNLOAD_GUIDE.md`, `packaging/BUILDING.md`, `docs/expansion-preview.svg`.
