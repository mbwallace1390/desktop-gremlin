Desktop Gremlin for Linux
=========================

1. Open [Desktop Gremlin releases](https://github.com/mbwallace1390/desktop-gremlin/releases).
2. Under Assets, download DesktopGremlin-3.1.0-Linux-x64.tar.gz.
3. Right-click the archive and choose Extract Here, then open its DesktopGremlin folder.
4. Double-click DesktopGremlin. If your file manager asks, choose Run.

Python, Tk and the required X11 client libraries are included. You do not need
Python, pip, a virtual environment or FUSE. Keep the _internal folder beside the
DesktopGremlin executable. The GitHub "Source code" downloads are for developers.

This download runs on a 64-bit x86 Linux computer with an X11 desktop and glibc
2.35 or newer, such as Ubuntu 22.04/24.04 in an Xorg session. It does not support
ARM computers or a Wayland session. If your login screen offers Ubuntu on Xorg,
choose that session before launching. The app reports unsupported sessions and
exits instead of covering the screen. It does not change your desktop session.

The gremlins interact with your actual desktop and compatible application
windows. Windows can be climbed and moved; Linux desktop icons are not moved.
Normal desktop clicks pass through the empty parts of the overlay.

Use the small Desktop Gremlin control window for Settings, Pause, Bring them to
my cursor, Put my windows back and Quit. Right-clicking a gremlin opens the same
menu. Ctrl+Alt+Shift+Q also quits when available; the control window shows its
availability. No terminal is needed during normal use.

If double-clicking does not launch the program, open the file's Properties,
enable its executable permission, then try again. You can also open a terminal
in the extracted DesktopGremlin folder and run:

```sh
chmod +x DesktopGremlin
./DesktopGremlin
```

Settings, memory and logs live in ~/.local/share/DesktopGremlin, or in
$XDG_DATA_HOME/DesktopGremlin when that location is configured. The startup
option uses ~/.config/autostart/DesktopGremlin.desktop, or the corresponding
$XDG_CONFIG_HOME/autostart location. These are per-user files; no administrator
access or background service is required.

To update, choose Put my windows back if needed, quit the old copy, extract the new
archive into a fresh folder and run its executable. Your saved preferences and
memory are reused. If Start when I sign in is enabled, open Settings in the new
copy and choose Apply before deleting the old folder; this updates the startup
entry to the new location.

To remove the app, disable its startup option if enabled, restore moved windows
and choose Quit. Delete the extracted application folder. Delete the per-user
DesktopGremlin data folder only if you also want to remove saved preferences
and memory. If a log is created, it is gremlin_log.txt in that folder.

If startup fails, confirm that you are in an X11 session and that the archive
was extracted completely. Keep the executable and its _internal directory
together. Download a fresh archive if files are missing.
