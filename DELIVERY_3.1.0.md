# Desktop Gremlin 3.1.0 — Linux desktop and native downloads

The Linux version interacts with the actual X11 desktop: gremlins use open
window frames as platforms, follow moving windows, react to focus and support
optional window nudges with verified restoration. All existing character,
weapon, movement, social and customization engines are shared with Windows.

Linux uses Tk drawing through X11 SHAPE. The overlay starts withdrawn with
empty bounding/input masks. Empty desktop space and decorative props pass
clicks to the application behind them. Fighter regions receive dragging input.
Clearing, hiding, shutdown and X11 failures release the overlay; a failed
presentation cannot schedule more work after shutdown. The background scanner
stops before its desktop connection closes and cannot reopen it after quit.

Linux has a small control window and Ctrl+Alt+Shift+Q when registration is
available. It supports XDG user storage and optional login startup. Labels use
contrasting plates suitable for shaped drawing. Windows continues using the
original Tk renderer; its quarantined native renderer remains disabled.

## Downloads

- `release/DesktopGremlin-3.1.0-Windows-x64.zip`
- `release/DesktopGremlin-3.1.0-Linux-x64.tar.gz`
- Matching `.sha256` and `.manifest.json` files accompany both archives.

These hashes describe the locally verified packages. GitHub rebuilds the
downloads on its native runners and provides matching checksum files with
each published release.

| Local archive | Compressed bytes | SHA-256 |
|---|---:|---|
| Windows ZIP | 16,531,873 | `8fdbf7bbf88cbce48dc093cfaa69a03be12ccdf142c5cf8b436f809dd6f54c42` |
| Linux tar.gz | 12,170,844 | `533b354be2779af977d7e1ee540ee564273876371282e1ad34e420d5c25f984d` |

Each includes Python, Tk, platform runtime libraries, licenses and
`README-FIRST.txt`. Users extract the entire folder and run the executable.
They do not install Python, pip, a virtual environment or FUSE.

Linux targets x86-64, glibc 2.35+ and an X11 session. It does not support generic
Wayland, ARM or Linux file-manager icon rearrangement. Compatibility with every
Linux desktop environment and graphics driver has not been established.

## Verification

- Windows: 41/41 regression suites passed; frozen diagnostic passed all 9 checks.
- Linux: 29/29 selected shared/Linux suites passed; the additional shutdown and
  retryable-restoration regressions passed (5/5 Linux runtime tests).
- Linux source and frozen diagnostics passed all 10 application checks plus
  all 4 cross-process input checks: empty-space delivery, fighter interaction,
  outside drag release and the global emergency shortcut.
- Real EWMH movement of a separately owned receiver window was observed and
  restored exactly. A separate process proved the Linux instance lock.
- Overlay acceptance covers actual clicks through cleared shapes and a real
  X11 BadDrawable failure. Its 6 checks passed under Xvfb/Openbox.
- All 14 runtime modules parse with Python 3.8 syntax. The source runs on Linux
  Python 3.10; Windows release uses Python 3.14.7.
- All five pre-existing settings/memory/backup/log/icon hashes remain unchanged.
- Fresh Windows and Linux archive extractions passed their frozen checks with
  Python absent from PATH. Their payload hashes remained unchanged afterward.
  Windows contains 1,011 files; Linux contains 404 files and retains executable
  mode 0755. Bundled main bytecode matches the final source on both platforms.
- Real Linux App drawing was inspected in
  `tests/.tmp/linux-overlay-visual-after.png`.

Native Linux verification used an isolated Xvfb/Openbox desktop in the dedicated
Ubuntu 22.04 WSL distribution `DesktopGremlinBuild-20260912`. No synthetic input
was delivered to the user's ordinary desktop. Xvfb acceptance is distinct from
hands-on acceptance on a physical Linux desktop.

Build evidence is retained in `build/windows/` and `build/linux/`, including
source/frozen JSON reports and fresh extracted-download verification.
Exact download reports are `build/windows/extracted-self-test-3.1.0.json`,
`build/windows/verified-download-3.1.0/verification.json`,
`build/linux/extracted-self-test.json` and `build/linux/verified-download.json`.
The dedicated WSL test distribution was stopped after verification; its build
environment remains available for future releases.

## GitHub and end-user delivery

`.github/workflows/release-downloads.yml` builds Windows and Linux on their
native runners. Both jobs must pass before a matching `v3.1.0` tag prepares one
draft release containing both archives and their integrity files. Manual runs
produce Actions artifacts. The workflow does not publish a release or replace
an existing release's files.

The local packaging verification above preceded GitHub publication. Published
downloads are available from the
[3.1.0 release](https://github.com/mbwallace1390/desktop-gremlin/releases/tag/v3.1.0)
under **Releases → Assets**. Its matching checksum files describe the GitHub builds.
GitHub's automatic **Source code** downloads are developer checkouts.

See `USER_DOWNLOAD_GUIDE.md`, `USER_DOWNLOAD_LINUX.md`, `packaging/BUILDING.md`
and `packaging/LINUX_BUILDING.md` for exact use and build commands.
