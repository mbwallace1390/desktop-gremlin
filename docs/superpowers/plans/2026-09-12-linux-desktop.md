# Linux desktop and cross-platform downloads

**Goal:** Deliver a Linux X11 desktop build using the existing complete gremlin
simulation, plus GitHub Actions builds for Windows and Linux.

**Authorization:** User explicitly chose actual desktop interaction over a
normal playground window. X11 is the first supported Linux session. Generic
Wayland integration and desktop-file-manager icon rearrangement are excluded
because neither has a portable equivalent to the Windows APIs used here.

**Architecture:** Keep shared simulation and Tk drawing. Guard Win32 setup;
Linux services provide real window geometry, pointer, monitors, movement and
exit handling. X11 SHAPE masks bound both the overlay and its input area.
The overlay starts withdrawn and fails closed. Windows quarantine is unchanged.

**Tech stack:** Existing Python/Tk; ctypes to system X11/SHAPE/Xrandr libraries.
PyInstaller bundles Python/Tk. Linux tar.gz targets Ubuntu 22.04+ x64 / compatible
glibc desktops. Xvfb, Openbox and XTest are build/test tools only.

## Tasks and ownership

- [x] Desktop services: gremlin_x11.py, tests/test_linux_desktop.py. Dedicated
  display, lock, EWMH windows/work areas, opt-in movement, pointer, close,
  bounded registration of Ctrl+Alt+Shift+Q. Handle disappearing windows.
- [x] Overlay and physical delivery: gremlin_x11_overlay.py,
  gremlin_x11_probe.py, tests/test_linux_overlay.py. Empty masks before mapping;
  Canvas-derived shapes; input only at gremlins; cleanup on hide/failure.
  Separate receiver process proves transparency, interaction, release and exit.
- [x] Root integration: desktop_gremlin.py, gremlin_linux.py,
  gremlin_linux_selftest.py, gremlin_paths.py, harness and runner. Real desktop
  geometry, safe control window, no unavailable icon controls, Linux data path,
  instance lock and diagnostic dispatch. Preserve all character engines.
- [x] Distribution: Linux spec/script/validator and unified GitHub workflow.
  Both OS jobs test/build on their native runners; a single gated job creates
  the draft release. No publishing or misleading unsupported-platform asset.
- [x] Validate Linux source and frozen executable under isolated Xvfb/Openbox,
  including cross-process input delivery, archived executable permissions,
  clean-PATH launch and private-file exclusion. Rerun Windows regression suites.
- [x] Deliver Linux and updated Windows archives, support/download guide,
  source/build evidence and explicit remaining real-desktop/Wayland limitations.

## Evidence ledger

- Existing 3.0.0 source and harness snapshots retained under tests/.tmp/linux_before.
- Official PyInstaller guidance requires native builds; GitHub supports native
  Windows/Linux runners. Tk -transparentcolor is Windows-only; Wayland does
  not expose other clients' surfaces/global coordinates generically.
- Verified official Ubuntu 22.04 root image and imported dedicated WSL distro
  DesktopGremlinBuild-20260912. All native input tests use isolated Xvfb.
- Linux: 29/29 suites, source/frozen 10 application and 4 input checks passed.
- Windows: 41/41 suites and frozen 9 checks passed.
- Both native archives created; exact download verification is recorded in
  DELIVERY_3.1.0.md and build/{windows,linux} reports.
- Source and downloads remain local; GitHub workflow publication is pending.
