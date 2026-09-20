# Linux release build

The Linux download runs on the actual X11 desktop. Build it on Ubuntu 22.04 x64
with its system Python 3.10 and matching Tk package. The resulting tar.gz bundles
Python, Tk and X11 client libraries; end users do not install Python or FUSE.
The host desktop still supplies X11 and glibc 2.35 or newer. Wayland and ARM are
outside this build's supported targets.

PyInstaller creates binaries for the operating system where it runs; it is
[not a cross-compiler](https://pyinstaller.org/en/stable/operating-mode.html).
It does not bundle glibc, so [build on the oldest supported Linux baseline](https://pyinstaller.org/en/stable/usage.html#making-gnu-linux-apps-forward-compatible).
Do not build the release on a newer distro and label it Ubuntu 22.04 compatible.

Install these **build-machine** dependencies:

```sh
sudo apt-get update
sudo apt-get install --yes python3.10-venv python3-tk xvfb xauth x11-utils openbox libx11-6 libxext6 libxtst6 libxrandr2 libxss1
/usr/bin/python3.10 -m venv .venv-linux
```

Run the complete build inside a dedicated virtual X server. The test moves a
synthetic pointer and verifies delivery to a separate receiver process, so do
not point it at your ordinary desktop display.

```sh
GREMLIN_ISOLATED_X11=1 XDG_SESSION_TYPE=x11 xvfb-run -a -s '-screen 0 1280x800x24 -nolisten tcp' bash -euo pipefail -c '
  openbox > /tmp/gremlin-build-openbox.log 2>&1 &
  window_manager=$!
  trap "kill $window_manager 2>/dev/null || true" EXIT
  for attempt in {1..50}; do
    if xprop -root _NET_SUPPORTING_WM_CHECK | grep -q "window id"; then break; fi
    sleep 0.1
  done
  xprop -root _NET_SUPPORTING_WM_CHECK | grep -q "window id"
  bash scripts/build_linux.sh
'
```

The script installs the exact build dependencies in requirements-build-linux.txt,
runs the Linux test selection and source self-test, builds DesktopGremlinLinux.spec,
and launches the frozen self-test from an unrelated temporary working directory.
The frozen gate removes Python from PATH and isolates HOME/XDG user files. It
requires all eleven app checks, including physics impulses, passive limb motion,
crate translation/rotation, actual window movement and restoration,
plus four X11 input checks: transparent pass-through,
opaque interaction, drag release outside the overlay and the emergency exit.
No package is created when any required check fails.
`gremlin_physics` and `gremlin_ragdoll` must load from the frozen bundle. The
isolated Settings window must save and reload both physics choices as well.

The spec explicitly collects ctypes-loaded X11/Xext/XTest/XRandR/XScreenSaver
libraries and their transitive dependencies. It excludes the Windows renderer
and Win32 modules. Tk's normal PyInstaller hook collects the matching Tcl/Tk
scripts. Runtime copyright notices are included with the bundle.

Outputs are dist/linux/DesktopGremlin, build/linux/*self-test.json, and these
release files (VERSION is read from desktop_gremlin.py):

- DesktopGremlin-VERSION-Linux-x64.tar.gz
- DesktopGremlin-VERSION-Linux-x64.sha256
- DesktopGremlin-VERSION-Linux-x64.manifest.json

The archive retains executable permissions and safe relative runtime symlinks.
Packaging rejects private runtime files, wrong architectures, missing libraries,
escaping or cyclic links, duplicate entries and invalid checksums. It archives
only the build folder plus the public guide and project license.

For local iteration, `--skip-install` reuses the virtual environment and
`--skip-tests` omits source regression suites. The source and frozen self-tests
still run. Use `--python /absolute/path/to/python` for another build virtual
environment. The release workflow does not skip tests.

# GitHub builds and end-user downloads

.github/workflows/release-downloads.yml runs separate native Windows and Linux
jobs. Both must pass before one matching version tag creates a single draft
release containing both downloads, checksums and manifests. A manual Actions
run stores workflow artifacts and does not create or publish a release.
GitHub's [artifact upload/download actions](https://docs.github.com/en/actions/tutorials/store-and-share-data)
transfer the two build results into the draft-release job.

After reviewing the source and approving its publication, commit and push it,
then create and push its matching version tag. For version 3.2.2:

```sh
git tag v3.2.2
git push origin v3.2.2
```

Wait for **Build Windows and Linux downloads** to finish, then open the draft
under [GitHub Releases](https://github.com/mbwallace1390/desktop-gremlin/releases).
Download both OS archives and inspect the retained self-test evidence. Check
the Linux archive before extracting it:

```sh
sha256sum --check DesktopGremlin-3.2.2-Linux-x64.sha256
tar -xzf DesktopGremlin-3.2.2-Linux-x64.tar.gz
```

Check startup, settings, ordinary desktop click-through, dragging, window undo
and quitting on a separate Linux X11 desktop without Python installed. Xvfb
provides automated cross-process input evidence; it does not prove compatibility
with every desktop environment, compositor or graphics driver. Inspect the six
download assets and notes, then publish the accepted draft. The workflow never
overwrites existing releases or publishes one automatically.

Users download the matching archive from **Releases → Assets**, extract it and
run the bundled executable. They do not need a developer checkout or an Actions
account once the release is public.
