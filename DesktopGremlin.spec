# Windows x64, one-folder, no console. PyInstaller bundles Python, Tk and pywin32.
from pathlib import Path
import importlib.metadata
import sys

ROOT = Path(SPECPATH)
sys.path.insert(0, str(ROOT / "packaging"))
from release import tk_resources

linux_modules = [path.stem for path in ROOT.glob("gremlin_*.py")
                 if path.stem.startswith(("gremlin_linux", "gremlin_x11"))]
application_modules = sorted(path.stem for path in ROOT.glob("gremlin_*.py")
                             if path.stem not in linux_modules)
runtime_notices = [
    (str(Path(sys.base_prefix) / "LICENSE.txt"), "licenses/Python"),
    (str(importlib.metadata.distribution("pywin32").locate_file("win32/License.txt")), "licenses/pywin32"),
]
runtime_notices += tk_resources(sys.base_prefix, ROOT / "build" / "windows" / "tk-resources")

analysis = Analysis(
    [str(ROOT / "desktop_gremlin.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=runtime_notices,
    hiddenimports=application_modules + ["tkinter.ttk", "win32timezone"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=linux_modules,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)
executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="DesktopGremlin",
    icon=str(ROOT / "packaging" / "app.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
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
