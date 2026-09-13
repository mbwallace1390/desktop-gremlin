Choose the download for your computer under Assets:

- Windows 10/11 x64: extract the Windows ZIP and run DesktopGremlin.exe.
- Linux x64 with an X11 desktop and glibc 2.35+: extract the Linux tar.gz and run
  DesktopGremlin. Ubuntu 22.04/24.04 Xorg sessions meet this baseline.

Python, Tk and the required platform libraries are included. No separate Python,
pip or FUSE installation is needed. Keep the _internal folder beside the
executable. The GitHub Source code archives are for developers.

This release adds seven cartoon weapons, friendships and group scenes,
parkour and playground toys, character profiles and Peaceful/Mischief/Battle modes.

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
