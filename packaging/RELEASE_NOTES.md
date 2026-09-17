Desktop Gremlin 3.2.1 reduces repeated physics and collision work and improves
performance measurements in both desktop downloads.

Choose the download for your computer under Assets:

- Windows 10/11 x64: download DesktopGremlin-3.2.1-Windows-x64.zip, extract it,
  and run DesktopGremlin.exe.
- Linux x64 with an X11 desktop and glibc 2.35+: download
  DesktopGremlin-3.2.1-Linux-x64.tar.gz, extract it, and run DesktopGremlin.
  Ubuntu 22.04/24.04 Xorg sessions meet this baseline.

Python, Tk and the required application libraries are included. No separate
Python, pip or FUSE installation is needed. Keep the _internal folder beside
the executable. GitHub's Source code archives are for developers.

This update:

- Reuses unchanged toy geometry and avoids repeated support checks for sleeping
  crates, while still responding to moved or removed supports and forces.
- Narrows projectile collision checks to nearby objects and directly locates
  explicit targets. Exact swept collisions, flight range and lifetime remain.
- Limits frame-thread waits for busy Windows Explorer and reuses validated
  recovery data. Live icon identity and durable undo protection are still
  checked before movement. A busy Explorer can interrupt a carry safely instead
  of making the interface wait for the full shell timeout.
- Includes Windows Tk painting in the drawing timer and separately reports
  frame intervals and simulation/drawing work in the Performance panel.
- Adds regression checks and full-feature performance coverage for mixed toys
  and crowded desktops.

Controlled Windows measurements found 21% less CPU work with ten gremlins and
mixed toys, 50% less with six crates, and 46% less with six crates and 400 icons.
These are repeated hidden-window measurements with a simulated desktop. They
do not establish visible desktop FPS, compositor/GPU cost, real Explorer speed
or Linux performance gains. The two-gremlin scene had no meaningful improvement.
See [the full measurements and verification](https://github.com/mbwallace1390/desktop-gremlin/blob/v3.2.1/docs/PERFORMANCE.md).

The 3.2 physics choices, weapons, friendships, group scenes, parkour, profiles
and Peaceful/Mischief/Battle modes remain available. Existing saved settings
are reused. To update, quit the old copy and extract the new download into a
fresh folder. If automatic startup is enabled, open Settings in the new copy
and choose Apply before removing the old folder.

Linux gremlins interact with the actual X11 desktop and compatible application
windows. The Linux build does not support Wayland, ARM or moving desktop icons.
Use its control window or right-click a gremlin for settings and quitting.
Ctrl+Alt+Shift+Q is the emergency exit when registered successfully. The Windows
native renderer remains disabled; normal startup uses Tk.

Windows data lives in %LOCALAPPDATA%\DesktopGremlin. Linux data lives in
~/.local/share/DesktopGremlin or $XDG_DATA_HOME/DesktopGremlin. Each extracted
download includes README-FIRST.txt with startup, update and removal instructions.

Each archive has a SHA-256 file and a per-file manifest. The Windows executable
is unsigned. GitHub prepares a draft only after both platform builds, source
tests and packaged checks pass. Automated checks use isolated desktops and do
not establish compatibility with every user's desktop or graphics driver.
