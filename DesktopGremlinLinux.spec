# Build on Ubuntu 22.04 x64. Python, Tk and the X11 client libraries are bundled.
from pathlib import Path
import importlib.metadata
import subprocess
import sys

ROOT = Path(SPECPATH)
sys.path.insert(0, str(ROOT / "packaging"))
from linux_release import x11_binaries

excluded = ["gremlin_renderer", "gremlin_selftest", "gremlin_frozen_selftest", "win32api", "win32gui", "win32con",
            "win32process", "win32event", "win32file", "win32timezone", "pywintypes", "pythoncom", "winreg"]
application_modules = sorted(path.stem for path in ROOT.glob("gremlin_*.py") if path.stem not in excluded)
runtime_notices = []
for package in ("python3.10", "libpython3.10", "libtcl8.6", "libtk8.6", "libx11-6", "libxext6",
                "libxtst6", "libxrandr2", "libxss1", "libxrender1", "libxcb1", "libxau6", "libxdmcp6",
                "zlib1g", "libexpat1", "libffi8", "libfontconfig1", "libfreetype6", "libpng16-16"):
    notice = Path("/usr/share/doc") / package / "copyright"
    if notice.is_file():
        runtime_notices.append((str(notice), "licenses/" + package))
if not any(destination == "licenses/python3.10" for _, destination in runtime_notices):
    raise RuntimeError("Build with Ubuntu 22.04's Python 3.10 and packaged runtime license notices")
pyinstaller_distribution = importlib.metadata.distribution("pyinstaller")
for entry in pyinstaller_distribution.files or []:
    if str(entry).endswith("/licenses/COPYING.txt"):
        runtime_notices.append((str(pyinstaller_distribution.locate_file(entry)), "licenses/PyInstaller"))

analysis = Analysis(
    [str(ROOT / "desktop_gremlin.py")],
    pathex=[str(ROOT)],
    binaries=x11_binaries(),
    datas=runtime_notices,
    hiddenimports=application_modules + ["tkinter.ttk"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded,
    noarchive=False,
    optimize=0,
)
# Retain the distro copyright notices for transitive libraries selected by
# analysis, including font/image libraries not imported directly by the app.
notice_destinations = {destination for _, destination in runtime_notices}
for _, source, _ in analysis.binaries:
    source_path = Path(source)
    candidate_paths = {str(source_path), str(source_path.resolve())}
    candidate_paths.update(path[4:] for path in list(candidate_paths) if path.startswith("/usr/lib/"))
    for candidate in candidate_paths:
        owner = subprocess.run(["dpkg-query", "-S", candidate], capture_output=True, text=True, check=False)
        if owner.returncode:
            continue
        for record in owner.stdout.splitlines():
            package = record.partition(": ")[0].partition(":")[0]
            notice = Path("/usr/share/doc") / package / "copyright"
            destination = "licenses/" + package
            if notice.is_file() and destination not in notice_destinations:
                analysis.datas.append((destination + "/copyright", str(notice), "DATA"))
                notice_destinations.add(destination)
        break
pyz = PYZ(analysis.pure)
executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="DesktopGremlin",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # Linux file-manager launches do not create a terminal window.
    contents_directory="_internal",
)
collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="DesktopGremlin",
)
