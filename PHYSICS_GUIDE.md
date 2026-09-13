# Desktop Gremlin 3.2 physics

Throws, impacts and playground toys now respond to momentum and surfaces.
Open Settings from the Windows tray menu or Linux control window, then use
**Physics** and **Surface feel** in Behaviour. Choose **Apply** to save.
Existing settings files use **normal** physics and **standard** surfaces until
you change them.

| Physics | Feel |
| --- | --- |
| normal | Default gravity and impact strength. |
| moon | Lower gravity, with longer airborne motion. |
| bouncy | Stronger rebounds and slightly stronger impulses. |
| heavy | Stronger gravity and weaker impulses. |

| Surface feel | Feel |
| --- | --- |
| standard | Default grip and modest bounce. |
| ice | Less grip and longer slides. |
| rubber | Springier landings. |
| sticky | Strong grip and little rebound. |

The choices combine: bouncy physics still encourages rebounds on a sticky
surface. Return both controls to normal/standard for the default behavior.
These settings affect the simulated gremlins and toys; they do not alter your
computer's mouse settings or window behavior.

## What changes on the desktop

- **Momentum and blasts.** Hits add impulses to existing velocity. Larger
  bodies resist the same impulse more; off-center hits add spin. Blast force
  follows the direction and distance from the blast, and can move crates.
- **Directional bounces.** Contacts respond to the surface normal and its
  friction and bounce. Swept projectile contacts check the travel between
  simulation positions, including the drawn polygons of crates, ramps and
  seesaws.
- **Passive limbs.** Grabs, throws and knockouts let four constrained,
  damped two-link limbs respond to gravity and root acceleration. Joint limits
  keep elbows and knees bounded, ground projection preserves limb lengths,
  and recovery blends back into idle animation. The torso/root still follows
  authored behavior; this is not a full rigid-body skeleton or limb collision
  system against every window and toy. Weapon and ledge-grip actions keep
  their authored poses.
- **Mouse throws.** Release velocity uses a short history of cursor samples,
  making the throw less dependent on the final mouse poll. Fast throws retain
  bounded speed and spin.
- **Physical toys.** Crates can translate, rotate, fall, receive impacts and
  settle into stacks. Settled crates wake if their support disappears. Crate
  terrain and stacking contacts use conservative boxes around the rotated
  shape; projectile contact uses the drawn polygon. Seesaws respond to rider
  weight and impacts around a fixed pivot. Ramps, fans and conveyors remain
  anchored. Fans lift bodies and crates; conveyors provide surface motion.
- **Body contacts.** Swept body checks catch fast motion at window sides and
  undersides. One-way platforms still support climbing and landings. Desktop
  objects remain simplified collision shapes rather than arbitrary app artwork.
- **Moving swings.** Pendulum motion follows a moving window anchor and carries
  its velocity into a release. Removed anchors end the swing. Rope behavior
  uses a constrained pendulum, not a chain of simulated rope segments.
- **Surface response.** Ice limits grip, rubber increases bounce and sticky
  surfaces dissipate motion. Physics presets adjust gravity and impulse
  strength across the participating engines.

Playground toys require **Build temporary playground toys**; swings require
**Parkour, swings and paper planes**. Peaceful mode keeps combat disabled while
letting you try mouse throws and playground activities. These are bounded
cartoon simulations with a fixed update step, capped objects and solver work.

Windows uses the existing Tk overlay; native Windows rendering remains
disabled. Linux uses Tk with X11 shapes on the actual desktop. Linux requires
an X11 session and does not support Wayland or desktop icon rearrangement.
Both release archives include Python and the application libraries.

## Validation

Source checks cover contact geometry, momentum, passive limbs, toys, swings,
mouse throws and mixed activity. The frozen-build `physics_engines` gate runs
an impulse, checks four changing passive limbs, and verifies crate translation
and rotation inside the existing isolated app. Both frozen self-tests save and
reload the Physics and Surface feel choices through Settings. These checks
are automated evidence; visual feel and compatibility with a particular
desktop environment remain separate acceptance checks.
