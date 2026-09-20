Desktop Gremlin 3.2.2 fixes a defect that permanently switched off the
friendship half of the cast's behaviour, and repairs several smaller problems.

Choose the download for your computer under Assets:

- Windows 10/11 x64: download DesktopGremlin-3.2.2-Windows-x64.zip, extract it,
  and run DesktopGremlin.exe.
- Linux x64 with an X11 desktop and glibc 2.35+: download
  DesktopGremlin-3.2.2-Linux-x64.tar.gz, extract it, and run DesktopGremlin.
  Ubuntu 22.04/24.04 Xorg sessions meet this baseline.

Python, Tk and the required application libraries are included. No separate
Python, pip or FUSE installation is needed. Keep the _internal folder beside
the executable. GitHub's Source code archives are for developers.

Grudges now wear off:

- Relationship scores only ever fell. Every landed hit deepened a grudge, no
  decay ever pulled one back, and the graph is saved between runs. Measured
  over twenty simulated minutes from an empty memory: 1171 falls against 2
  rises, with fourteen of fifteen pairs stuck at the minimum by minute eight.
- Rescues, alliances and the quiet group scenes all require a neutral or
  positive score, so once a pair bottomed out those behaviours were locked out
  for good, and only "Make them forget everything about me" cleared it.
- A fight now deepens a grudge once every few seconds rather than once per
  landed blow, and fighting alone can no longer drive a pair past a fixed
  rivalry bound however long it goes on. Scores also fade back toward neutral
  as a run continues: grudges quickly, friendships slowly. Rivalries still
  form during sustained fighting; they can now be got over.
- Saved grudges from earlier versions thaw on their own over the first few
  minutes of a run. No settings or memory file needs to be deleted.
- Group scenes remain uncommon, because they need the cast idle to start. This
  release removes the permanent lockout; it does not make them frequent.

Also in this update:

- An unrecognised command-line option now reports itself when Desktop Gremlin
  is started without a console, instead of exiting silently.
- The Windows startup-entry helper no longer leaks a registry handle when
  writing that entry fails.
- The Performance panel rejects a non-finite simulation-step count.
- Passive limb geometry clamps its squash factor rather than relying on every
  caller to stay in range.
- The check runner now reports how many tests were skipped rather than
  counting a skipped check as a full pass, and the per-push continuous
  integration run uses the same Python version the downloads are built with.

The 3.2 physics choices, weapons, friendships, group scenes, parkour, profiles
and Peaceful/Mischief/Battle modes remain available. Existing saved settings
are reused. To update, quit the old copy and extract the new download into a
fresh folder. If automatic startup is enabled, open Settings in the new copy
and choose Apply before removing the old folder.

The 3.2.1 performance work is unchanged and still applies. See
[the full measurements and verification](https://github.com/mbwallace1390/desktop-gremlin/blob/v3.2.2/docs/PERFORMANCE.md).

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
