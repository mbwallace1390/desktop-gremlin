# Desktop Gremlin full feature expansion

The user approved every feature in the preceding proposal. Implementation is
authorized in the current workspace, preserving all uncommitted audit fixes.

## Accepted behavior

- Seven weapons: returning/catchable boomerang with owner-bonk risk, bubble
  cannon with floating/poppable victims, sliding freeze cubes, position swap
  gun, recoil-heavy boxing glove, bounded ricocheting rubber balls, and sticky
  foam from which another gremlin can free a friend.
- Persistent pairwise friendships/rivalries, temporary alliances that can
  break on friendly fire, rescues of falling/KO/stuck friends, staged hat heists,
  fake surrender with a dropped trap, spectators with scorecards, grudge court,
  and cards/football/juggling/blanket naps/coffee activities.
- Pendulum rope swinging, wall kicks/landing rolls/vaults/projectile slides,
  paper-plane travel with landing/crash, team boosts, interactive crates,
  seesaws/ramps/fans/conveyors, and window-resize inspector scenes.
- Select any subset of the ten cast members, per-character nickname/color/hat/
  allowed weapons, Peaceful/Mischief/Battle modes, reusable timed status effects
  including shields, and a bounded scene coordinator.

## Constraints

- Python 3.8-compatible syntax, Tk and pywin32; no added dependencies/services.
- Native renderer stays quarantined. No new global capture, focus stealing,
  external automation, real-file toy props, or bypass of movement backup gates.
- One to ten distinct stable roster identities; existing saved settings and
  counters load unchanged. New settings use additive defaults.
- Props, scenes, relationships, effects and projectiles have bounded ownership,
  lifetime/count, and cleanup on interruption/removal/hide. Persistent social
  state stores only roster identifiers and bounded scores, never window titles.
- Tests use the shared harness, fake desktop boundaries and owned Tk windows.
- Normal startup provides the new features; toggles/modes expose control.
- No commits or push: the current workspace contains the user's ongoing work.

## Module boundaries

`gremlin_arsenal.py` owns new weapon projectiles/status effects; public
`Arsenal(app, cfg)`, `release(f) -> bool`, `update(dt)`, `control(f, dt) -> bool`,
`draw()`, `clear(f=None)`, `apply_effect(f, kind, duration, source=None)`,
`filter_damage(att, vic, dmg) -> float`. States and images stay on the existing
Tk canvas. Its drawing layer is `arsenal`.

`gremlin_motion.py` owns new traversal and toy props; public
`MotionEngine(app, cfg)`, `consider(f) -> bool`, `update(dt)`,
`control(f, dt) -> bool`, `draw()`, `clear(f=None)`,
`start(f, kind, target=None) -> bool`, `add_prop(kind, x, y) -> dict or None`,
`platforms() -> list[(left,right,top,"toy",id)]`. Drawing layer `toys`.

`gremlin_social.py` owns relationships and bounded group scenes; public
`SocialDirector(app, cfg, memory_getter, mark_dirty)`, `update(dt)`,
`control(f, dt) -> bool`, `draw()`, `clear(f=None)`,
`on_hit(att,vic,dmg)`, `affinity(a,b) -> number`,
`start_scene(kind, actors=None) -> bool`, `on_windows_changed(old,new)`.
Scene drawing layer `social`. Memory getter returns the current memory dict
so Forget cannot retain a stale object; mark_dirty takes no arguments.

Root owns constructors/lifecycle and update/draw hooks, cast/profiles/modes,
settings and saved-memory integration, runner, documentation and final review.
Weapon implementer owns combat tables, weapon pose/draw/release hooks and damage
filter integration. Motion/social implementers own their new modules only;
root adds their main-file hooks to avoid overlapping structural edits.

## Defaults and UI

Mode `mischief`; scenes, parkour and toy props on. Existing crowd still sets
the count; empty cast preference retains the traditional prefix selection.
An explicit cast list determines selected identities. Character profiles
default to each existing appearance and temperament. Nicknames do not replace
stable persistence keys. Allowed weapon lists are respected by AI selection.

Peaceful suppresses attacks, damage and hostile scenes while allowing travel,
rescue and quiet activities. Mischief balances scenes/play with fights. Battle
increases combat frequency while retaining readable cooldowns. Mode changes
cancel incompatible active actions and ammunition.

## Added distribution requirement

After the four feature subsystems are complete, produce a self-contained
Windows download bundling the interpreter, Tk and pywin32. End users should
not install Python or dependencies. At the end, establish the GitHub release
download route and clear instructions for using the artifact. Build and local
verification are authorized; public publishing remains a separate final step.
