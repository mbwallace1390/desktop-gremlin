# Windows release build

From a Windows x64 checkout with Python 3.14.7:

```powershell
python -m venv .venv
./scripts/build_windows.ps1
```

The script installs the exact versions in requirements-build.txt, runs the full
test suite, builds a windowed one-folder executable, and launches its bounded
`--self-test` from a clean temporary working directory with Python removed from
PATH. It packages a ZIP, SHA-256 checksum and per-file manifest only after that
test reports a frozen application, all modules loaded, Tk and disabled native
rendering. The build report stays in build/windows/packaged-self-test.json.
The required `physics_engines` check exercises an impulse, four passive limbs
and crate translation/rotation. Both physics modules must originate inside the
bundle; the isolated Settings window must also save and reload both new choices.

`-SkipInstall` reuses the build environment. `-SkipTests` skips source tests for
local iteration; the frozen executable smoke test still runs. Neither switch is
used by the release workflow. Outputs are build/windows, dist/windows and release.

The unified .github/workflows/release-downloads.yml workflow runs on manual
dispatch or a `vVERSION` tag. It builds Windows and Linux on separate native
runners. A manual run keeps downloadable workflow artifacts. A matching tag
creates one draft GitHub release only after both jobs pass; it does not publish
automatically or replace existing release assets. No signing certificate is
configured. See [Linux build instructions](LINUX_BUILDING.md) for the X11 target.

The ZIP is created from the PyInstaller output folder alone, plus the public
download guide and license. Runtime settings, icon backup, memory and logs are
rejected. The executable is checked for the Windows GUI subsystem, x64 machine
type and required bundled Python/Tk/pywin32 resources.

PyInstaller includes the Python interpreter and dependencies in the distribution;
it is not a Windows cross-compiler. Python 3.14 support was introduced in 6.15.
The selected version is 6.22.3. See the official
[operating model](https://pyinstaller.org/en/stable/operating-mode.html),
[changelog](https://pyinstaller.org/en/stable/CHANGES.html),
[spec files](https://pyinstaller.org/en/stable/spec-files.html) and
[runtime path guidance](https://pyinstaller.org/en/stable/runtime-information.html).

Python 3.14.7 ships Tcl/Tk 9 with script archives. DLL-only relocation failed the
actual packaged Tk test in this environment, so the spec stages those archives
as _tcl_data and _tk_data. PyInstaller's standard runtime hook then supplies their
paths. No application runtime workaround or installed Python path is required.

## Maintainer publication checklist

The local build does not publish anything. After reviewing the changes and
authorizing their publication:

1. Commit and push the reviewed source, packaging files, app.ico and workflow.
2. Check that desktop_gremlin.py declares the intended VERSION, then create and
   push its matching tag, for example `git tag v3.3.1` followed by
   `git push origin v3.3.1`. The tag must point at the reviewed source commit.
3. Wait for **Build Windows and Linux downloads** in GitHub Actions. Both native
   builds require source tests, executable smoke tests and archive checks to
   pass before one draft release is created. A manual run produces workflow
   artifacts only.
4. Open the draft under [GitHub Releases](https://github.com/mbwallace1390/desktop-gremlin/releases).
   Download its Windows ZIP and SHA-256 file. Check the ZIP using
   `Get-FileHash -Algorithm SHA256 <downloaded ZIP path>`, then extract it and
   confirm startup/settings/quit on a clean Windows machine without Python.
5. Inspect the draft title, notes and six assets (one archive, SHA-256 and
   manifest per operating system). Verify the Linux download using its guide.
   Choose **Publish release** only after the download is accepted. Existing
   releases are never overwritten by the workflow.

The source checks and packaged fake-desktop smoke test do not claim acceptance
on an unrelated user's Windows installation. Test the release on a clean Windows
machine before treating that separate distribution check as complete.
