Desktop Gremlin 3.3.0 fixes several things that were drawn wrong, and tidies
the look of the gremlins, their speech and the Settings window.

Choose the download for your computer under Assets:

- Windows 10/11 x64: download DesktopGremlin-3.3.0-Windows-x64.zip, extract it,
  and run DesktopGremlin.exe.
- Linux x64 with an X11 desktop and glibc 2.35+: download
  DesktopGremlin-3.3.0-Linux-x64.tar.gz, extract it, and run DesktopGremlin.
  Ubuntu 22.04/24.04 Xorg sessions meet this baseline.

Python, Tk and the required application libraries are included. No separate
Python, pip or FUSE installation is needed. Keep the _internal folder beside
the executable. GitHub's Source code archives are for developers.

Drawn right:

- Hovering over a gremlin printed two names on top of each other, "the zealot"
  and "Zealot", so neither could be read. There is now one name tag, centred
  under the gremlin and kept on the screen, showing its nickname.
- The bow was drawn as a near-closed ring around the fist. It is now held by
  its grip, with the string drawn back to the other hand and an arrow nocked
  until the shot; the arrow leaves from the grip.
- A speech bubble's tail was about three pixels long at the default size, so
  it could not be seen, and two gremlins talking side by side covered each
  other's words. The tail now points at whoever is talking, a bubble that
  would overlap another moves clear of it (the one already showing stays
  put), bubbles no longer hide the speaker's health bar, and a gremlin
  spinning through the air no longer takes his bubble round with him.
- A large gremlin could only be picked up round the middle: the grab reach was
  the same 62 pixels at every size. It now grows with gremlins above size 1.24,
  as do the hover rings, so a big one can be grabbed by the head or the feet.
  Nothing changes at the default size.
- Playground toys printed a small caption ("SEESAW", "RAMP") onto the desktop
  under each one. They no longer do.

Looks better:

- Sleeping gremlins snore: small z's drift up from their heads.
- Windows: speech bubbles are rounded, and a name's letters get a dark
  outline so a pale name reads on a light wallpaper without a plate that would
  catch clicks meant for your desktop.
- Windows: Settings is dark throughout. The tabs, drop-down lists and text
  boxes match the window, the Cast tab lost its grey borders, and Settings
  and Performance show the gremlin icon in a dark title bar.
- Windows: the tray icon is drawn at exactly the size your display scaling
  asks for, whatever it is, with a dark edge that keeps it visible on a light
  taskbar. The program icon now carries sizes from 16 to 256 pixels for
  shortcuts, the taskbar and File Explorer.

On Linux, the X11 overlay only shapes lines, ovals, rectangles and text, so
speech bubbles stay rectangular there, names keep their label plate, and the
Linux theme of the Settings tabs is unchanged.

Drawing costs about the same. On the development machine a fixed scene of ten
gremlins, four talking, one hovered, one asleep and one fighting took 2.95 ms
to draw and paint per frame, against 2.72 ms for 3.2.2, out of a 25 ms frame;
the hovered gremlin's outlined name is most of the difference.

The 3.2 physics choices, weapons, friendships, group scenes, parkour, profiles
and Peaceful/Mischief/Battle modes remain available. Existing saved settings
are reused. To update, quit the old copy and extract the new download into a
fresh folder. If automatic startup is enabled, open Settings in the new copy
and choose Apply before removing the old folder.

Also new if you are coming from 3.2.1. Version 3.2.2 was never published on
its own, so its fixes arrive with this release:

- Grudges now wear off. Relationship scores used to only ever fall: every
  landed hit deepened a grudge, nothing pulled one back, and the scores are
  saved between runs. Within about ten minutes of play every pair was stuck at
  the minimum for good, which locked out rescues, alliances and the quiet group
  scenes, and only "Make them forget everything about me" cleared it.
- A fight now deepens a grudge once every few seconds instead of once per
  blow, fighting alone can no longer push a pair past a fixed rivalry bound,
  and scores fade back toward neutral as a run goes on: grudges quickly,
  friendships slowly. Rivalries still form, and can now be got over.
- Grudges saved by an earlier version thaw on their own over the first few
  minutes of a run; nothing needs deleting. Group scenes are still uncommon,
  because they need the cast idle, but they are no longer locked out.
- An unrecognised command-line option now says so when Desktop Gremlin runs
  without a console, instead of exiting silently, and a failed Windows startup
  entry no longer leaks a registry handle.

The 3.2.1 performance work still applies. See
[the full performance measurements and verification](https://github.com/mbwallace1390/desktop-gremlin/blob/v3.3.0/docs/PERFORMANCE.md).

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
