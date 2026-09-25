Desktop Gremlin 3.3.1 fixes crowded speech and Settings on small screens, and
gives Mischief gremlins time for shared activities between fights.

Choose the download for your computer under Assets:

- Windows 10/11 x64: download DesktopGremlin-3.3.1-Windows-x64.zip, extract it,
  and run DesktopGremlin.exe.
- Linux x64 with an X11 desktop and glibc 2.35+: download
  DesktopGremlin-3.3.1-Linux-x64.tar.gz, extract it, and run DesktopGremlin.
  Ubuntu 22.04/24.04 Xorg sessions meet this baseline.

Python, Tk and the required application libraries are included. No separate
Python, pip or FUSE installation is needed. Keep the _internal folder beside
the executable. GitHub's Source code archives are for developers.

Changes in 3.3.1:

- Crowded speech bubbles search for free space instead of repeatedly pushing
  into neighboring bubbles. Several gremlins talking near the top of the screen
  no longer end up with their messages drawn in the same place.
- Settings fits the available desktop and can be resized. Each tab scrolls,
  keyboard focus reveals its controls, and Apply and Close remain visible on
  small screens and with larger fonts.
- In Mischief mode with group scenes enabled, fights have bounded quiet breaks
  that give shared activities a chance to start. Battle mode keeps its existing
  pace, and disabling group scenes retains the previous behavior.
- The test runner rejects unknown options, misspelled check names and checks
  unavailable on the current platform instead of silently testing a subset.
  Shared visual checks now run on actual isolated Linux X11, and pushes and
  pull requests run both Windows and Linux checks.
- The playground preview shows its pendulum swing again and verifies that the
  staged rope action is still active before exporting the image.

The 3.3.0 visual improvements and earlier physics, performance and relationship
fixes remain included. Windows native rendering remains disabled; normal
startup uses Tk. Linux gremlins interact with the actual X11 desktop and
compatible application windows. Linux does not support Wayland, ARM or moving
desktop icons. Ctrl+Alt+Shift+Q is the emergency exit when registered successfully.

To update, restore any moved windows if needed, quit the old copy, extract the
new download into a fresh folder and run it. Saved settings and memory are
reused. If automatic startup is enabled, open Settings in the new copy and
choose Apply before deleting the old folder so the startup entry uses its new
location.

Windows data lives in %LOCALAPPDATA%\DesktopGremlin. Linux data lives in
~/.local/share/DesktopGremlin or $XDG_DATA_HOME/DesktopGremlin. Each extracted
download includes README-FIRST.txt with startup, update and removal instructions.

Each archive has a SHA-256 file and a per-file manifest. The Windows executable
is unsigned. GitHub prepares a draft only after both platform builds, source
tests and packaged checks pass. Automated checks use isolated desktops and do
not establish compatibility with every user's desktop or graphics driver.
