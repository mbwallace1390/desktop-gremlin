"""Build-owned Windows archive validation, checksums and isolated smoke launch."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
import subprocess
import tempfile
import zipfile


PRIVATE_NAMES = frozenset(("gremlin_settings.json", "gremlin_icon_backup.json",
                           "gremlin_memory.json", "gremlin_log.txt", "gremlin.ico"))
MODULES = frozenset(("gremlin_renderer", "gremlin_performance", "gremlin_profiles",
                     "gremlin_arsenal", "gremlin_motion", "gremlin_social",
                     "gremlin_physics", "gremlin_ragdoll"))
SMOKE_CHECKS = frozenset(("single_instance", "bundled_imports", "owned_withdrawn_tk",
                          "simulation_and_canvas", "expansion_engines", "physics_engines", "settings_roundtrip",
                          "memory_roundtrip", "hide_cleanup", "emergency_exit_dispatch"))


def tk_resources(python_root, staging):
    """Collect CPython's Tcl/Tk 9 script archives into normal hook directories.

    DLL-only relocation failed the frozen Tk smoke test on Python 3.14.7.
    Explicit scripts let PyInstaller's ordinary Tk runtime hook set its paths.
    Older installations with loose libraries continue through the stock hook.
    """
    python_root, staging = Path(python_root), Path(staging).resolve()
    result = []
    for kind, root_entry, destination in (("tcl", "tcl_library", "_tcl_data"),
                                          ("tk", "tk_library", "_tk_data")):
        archives = sorted((python_root / "tcl").glob("lib%s*.zip" % kind))
        if not archives:
            continue
        if len(archives) != 1:
            raise ValueError("Ambiguous Tcl/Tk runtime archives for " + kind)
        target = staging / archives[0].stem
        with zipfile.ZipFile(archives[0]) as archive:
            entries = []
            for entry in archive.infolist():
                path = PurePosixPath(entry.filename)
                if ("\\" in entry.filename or ":" in entry.filename or path.is_absolute()
                        or ".." in path.parts or not path.parts or path.parts[0] != root_entry):
                    raise ValueError("Unsafe Tcl/Tk resource archive entry")
                if not entry.is_dir():
                    entries.append((entry, Path(*path.parts[1:])))
            for entry, relative in entries:
                output = target / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(archive.read(entry))
        required = "init.tcl" if kind == "tcl" else "tk.tcl"
        if not (target / required).is_file():
            raise ValueError("Tcl/Tk archive has no " + required)
        result.append((str(target), destination))
    return result


def digest(path):
    result = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _windowed_pe(data):
    try:
        offset = struct.unpack_from("<I", data, 60)[0]
        signature = data[offset:offset + 4]
        machine = struct.unpack_from("<H", data, offset + 4)[0]
        magic = struct.unpack_from("<H", data, offset + 24)[0]
        subsystem = struct.unpack_from("<H", data, offset + 24 + 68)[0]
    except (struct.error, ValueError):
        raise ValueError("Executable has an incomplete Windows PE header")
    if data[:2] != b"MZ" or signature != b"PE\0\0" or machine != 0x8664 or magic != 0x20b:
        raise ValueError("Expected a Windows x64 executable")
    if subsystem != 2:
        raise ValueError("Release executable must use the windowed subsystem")


def _safe_name(name):
    path = PurePosixPath(name)
    if (not name or "\\" in name or ":" in name or path.is_absolute()
            or any(part in (".", "..") for part in path.parts)
            or path.parts[0] != "DesktopGremlin"):
        raise ValueError("Unsafe archive path: " + name)
    if any(part.lower() in PRIVATE_NAMES for part in path.parts):
        raise ValueError("Personal runtime data cannot be distributed: " + name)
    return path


def validate_bundle(bundle):
    bundle = Path(bundle).resolve()
    executable = bundle / "DesktopGremlin.exe"
    if not executable.is_file() or not (bundle / "_internal").is_dir():
        raise ValueError("Missing DesktopGremlin.exe or its _internal runtime folder")
    _windowed_pe(executable.read_bytes()[:4096])
    files = []
    for path in sorted(bundle.rglob("*")):
        if path.is_symlink():
            raise ValueError("Release bundle cannot contain symbolic links")
        if not path.is_file():
            continue
        relative = path.relative_to(bundle)
        _safe_name("DesktopGremlin/" + relative.as_posix())
        files.append(path)
    names = {path.name.lower() for path in files}
    for required in ("_tkinter.pyd", "win32gui.pyd", "win32api.pyd"):
        if required not in names:
            raise ValueError("Bundle is missing required runtime file: " + required)
    loose_tk = {"init.tcl", "tk.tcl"}.issubset(names)
    embedded_tk = {"tcl90.dll", "tcl9tk90.dll"}.issubset(names)
    # CPython's current Tk 9 build embeds these scripts in the two DLLs.
    # The following frozen smoke test verifies that Tk can actually load them.
    if not loose_tk and not embedded_tk:
        raise ValueError("Bundle has neither Tcl/Tk scripts nor embedded Tk 9 resources")
    if not any(re.fullmatch(r"python3\d+\.dll", name) for name in names):
        raise ValueError("Bundle is missing its Python interpreter DLL")
    return files


def validate_smoke_report(report, expected_version=None):
    if not isinstance(report, dict) or report.get("ok") is not True:
        raise ValueError("Packaged self-test did not pass")
    if report.get("frozen") is not True or report.get("native_enabled") is not False or report.get("renderer") != "tk":
        raise ValueError("Self-test did not prove a frozen Tk-only application")
    modules = report.get("modules", [])
    if not isinstance(modules, (list, dict)) or not MODULES.issubset(set(modules)):
        raise ValueError("Packaged self-test did not load every application module")
    checks = report.get("checks")
    if (not isinstance(checks, dict) or not SMOKE_CHECKS.issubset(checks)
            or any(value is not True for value in checks.values())):
        raise ValueError("Packaged self-test contains missing or failed checks")
    if expected_version is not None and report.get("version") != expected_version:
        raise ValueError("Packaged executable version does not match the release version")
    return report


def smoke(bundle, report_path, timeout=60, expected_version=None):
    bundle, report_path = Path(bundle).resolve(), Path(report_path).resolve()
    validate_bundle(bundle)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if report_path.exists():
        report_path.unlink()
    # No project working directory, Python search path or installed Python in
    # PATH may rescue a missing bundled dependency during the release gate.
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    windows = Path(env.get("SystemRoot", r"C:\Windows"))
    env["PATH"] = str(windows / "System32") + os.pathsep + str(windows)
    with tempfile.TemporaryDirectory(prefix="clean launch ", dir=report_path.parent) as working:
        process = subprocess.run([str(bundle / "DesktopGremlin.exe"), "--self-test", str(report_path)],
                                 cwd=working, env=env, timeout=timeout, check=False,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if process.returncode != 0:
        raise RuntimeError("Packaged self-test exited with code %s; see %s" % (process.returncode, report_path))
    if not report_path.is_file():
        raise RuntimeError("Packaged self-test returned without its report")
    return validate_smoke_report(json.loads(report_path.read_text(encoding="utf-8")), expected_version)


def package(bundle, output, version, guide, license_path):
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?", version):
        raise ValueError("Version must be a numeric release version")
    bundle, output = Path(bundle).resolve(), Path(output).resolve()
    files = validate_bundle(bundle)
    if output == bundle or bundle in output.parents:
        raise ValueError("Release output must be outside the application bundle")
    output.mkdir(parents=True, exist_ok=True)
    stem = "DesktopGremlin-%s-Windows-x64" % version
    archive_path = output / (stem + ".zip")
    manifest = {"version": version, "platform": "Windows-x64", "files": []}
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = "DesktopGremlin/" + path.relative_to(bundle).as_posix()
            archive.write(path, relative)
            manifest["files"].append({"path": relative, "bytes": path.stat().st_size, "sha256": digest(path)})
        for document, filename in ((Path(guide), "README-FIRST.txt"), (Path(license_path), "LICENSE.txt")):
            archive.write(document, "DesktopGremlin/" + filename)
            manifest["files"].append({"path": "DesktopGremlin/" + filename,
                                       "bytes": document.stat().st_size, "sha256": digest(document)})
    checksum_path = output / (stem + ".sha256")
    checksum_path.write_text(digest(archive_path) + "  " + archive_path.name + "\n", encoding="ascii")
    manifest_path = output / (stem + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    verify_archive(archive_path, checksum_path)
    return {"zip": str(archive_path), "checksum": str(checksum_path), "manifest": str(manifest_path)}


def verify_archive(archive_path, checksum_path=None):
    archive_path = Path(archive_path)
    if checksum_path:
        expected = Path(checksum_path).read_text(encoding="ascii").strip().split()
        if len(expected) != 2 or expected[1] != archive_path.name or expected[0] != digest(archive_path):
            raise ValueError("Release archive checksum does not match")
    with zipfile.ZipFile(archive_path) as archive:
        seen = set()
        total = 0
        for entry in archive.infolist():
            _safe_name(entry.filename)
            key = entry.filename.lower()
            if key in seen:
                raise ValueError("Duplicate Windows archive path: " + entry.filename)
            seen.add(key)
            total += entry.file_size
        if archive.testzip() is not None:
            raise ValueError("Release archive failed its ZIP integrity check")
        executable = "DesktopGremlin/DesktopGremlin.exe"
        if executable.lower() not in seen:
            raise ValueError("Release archive has no executable")
        _windowed_pe(archive.read(executable)[:4096])
    return {"files": len(seen), "bytes": total, "sha256": digest(archive_path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    packed = commands.add_parser("package")
    packed.add_argument("--bundle", required=True)
    packed.add_argument("--output", required=True)
    packed.add_argument("--version", required=True)
    packed.add_argument("--guide", required=True)
    packed.add_argument("--license", required=True)
    checked = commands.add_parser("smoke")
    checked.add_argument("--bundle", required=True)
    checked.add_argument("--report", required=True)
    checked.add_argument("--version", required=True)
    args = parser.parse_args()
    if args.command == "smoke":
        result = smoke(args.bundle, args.report, expected_version=args.version)
    else:
        result = package(args.bundle, args.output, args.version, args.guide, args.license)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
