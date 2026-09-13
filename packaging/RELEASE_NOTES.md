Desktop Gremlin 3.2.0 brings a physics update to both desktop downloads.

Choose the download for your computer under Assets:

- Windows 10/11 x64: extract the Windows ZIP and run DesktopGremlin.exe.
- Linux x64 with an X11 desktop and glibc 2.35+: extract the Linux tar.gz and run
  DesktopGremlin. Ubuntu 22.04/24.04 Xorg sessions meet this baseline.

Python, Tk and the required platform libraries are included. No separate Python,
pip or FUSE installation is needed. Keep the _internal folder beside the
executable. The GitHub Source code archives are for developers.

Hits and blasts now add mass-aware momentum and spin. Contacts bounce in the
surface direction, fast bodies check window edges, and projectiles check toy
polygons. Mouse throws use recent cursor motion. Four constrained passive limbs
respond during grabs, throws and knockouts, then recover into authored animation.

Crates move, rotate and stack; seesaws respond to weight around an anchored
pivot. Moving window anchors carry pendulum swings and their release velocity.
Crate terrain/stack contacts use conservative boxes; projectile contacts use
the drawn polygon. Other toys remain anchored, and the fighter root remains
authored rather than a full rigid-body skeleton.

Settings now includes Physics (normal, moon, bouncy, heavy) and Surface feel
(standard, ice, rubber, sticky). Normal/standard are the defaults. The existing
cartoon weapons, friendships, group scenes, parkour, profiles and
Peaceful/Mischief/Battle modes remain available.

Linux gremlins interact with the actual X11 desktop and compatible application
windows. The Linux build does not support Wayland, ARM or moving desktop icons.
Use its control window or right-click a gremlin for settings and quitting.
Ctrl+Alt+Shift+Q is the emergency exit on both platforms. The Windows native
renderer remains disabled.

Windows data lives in %LOCALAPPDATA%\DesktopGremlin. Linux data lives in
~/.local/share/DesktopGremlin or $XDG_DATA_HOME/DesktopGremlin. Each extracted
download includes README-FIRST.txt with startup, update and removal instructions.

Each archive has a SHA-256 file and a manifest. The Windows executable is
unsigned. The pipeline prepares one draft after both platform builds and their
packaged checks pass; the maintainer reviews the downloads before publication.
Both packaged self-tests require the new physics modules, exercise impulses,
passive limbs and crate motion, and save/reload the new Settings choices.
