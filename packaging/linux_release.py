"""Validate, smoke-test and archive the self-contained Linux X11 download."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import struct
import subprocess
import tarfile
import tempfile

PRIVATE_NAMES = frozenset(("gremlin_settings.json", "gremlin_icon_backup.json", "gremlin_memory.json",
                           "gremlin_log.txt", "gremlin.ico"))
MODULES = frozenset(("gremlin_performance", "gremlin_profiles", "gremlin_arsenal", "gremlin_motion",
                     "gremlin_social", "gremlin_linux", "gremlin_x11", "gremlin_x11_overlay",
                     "gremlin_physics", "gremlin_ragdoll"))
SMOKE_CHECKS = frozenset(("single_instance", "bundled_imports", "owned_withdrawn_tk", "simulation_and_canvas",
                          "expansion_engines", "physics_engines", "settings_roundtrip", "memory_roundtrip", "hide_cleanup",
                          "emergency_exit_dispatch", "window_tracking_and_restore"))
DESKTOP_CHECKS = frozenset(("transparent_passthrough", "opaque_interaction", "outside_drag_release", "emergency_exit"))
X11_LIBRARIES = ("libX11.so.6", "libXext.so.6", "libXtst.so.6", "libXrandr.so.2", "libXss.so.1")


def digest(path):
    hashed = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hashed.update(chunk)
    return hashed.hexdigest()


def _linux_elf(data):
    if len(data) < 64 or data[:7] != b"\x7fELF\x02\x01\x01":
        raise ValueError("Expected a Linux little-endian 64-bit ELF executable")
    kind, architecture, version = struct.unpack_from("<HHI", data, 16)
    if kind not in (2, 3) or architecture != 62 or version != 1:
        raise ValueError("Expected a Linux x86-64 executable")


def _safe_name(name):
    path = PurePosixPath(name)
    if (not name or "\\" in name or ":" in name or path.is_absolute() or ".." in path.parts
            or not path.parts or path.parts[0] != "DesktopGremlin"
            or name != path.as_posix()):
        raise ValueError("Unsafe archive path: " + name)
    if any(part.lower() in PRIVATE_NAMES for part in path.parts):
        raise ValueError("Personal runtime data cannot be distributed: " + name)
    return path


def _link_target(name, target):
    if not target or "\\" in target or ":" in target or PurePosixPath(target).is_absolute():
        raise ValueError("Archive link must be relative: " + name)
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
    _safe_name(resolved)
    return resolved


def _required_runtime(names):
    basenames = {PurePosixPath(name).name for name in names}
    missing = set(X11_LIBRARIES + ("init.tcl", "tk.tcl")) - basenames
    if missing:
        raise ValueError("Missing required Linux runtime: " + ", ".join(sorted(missing)))
    if not any(re.fullmatch(r"libpython3\.\d+\.so(?:\.\d+)*", name) for name in basenames):
        raise ValueError("Bundle is missing the Python shared library")
    if not any(name.startswith("_tkinter.") and name.endswith(".so") for name in basenames):
        raise ValueError("Bundle is missing the Tkinter extension")


def validate_bundle(bundle):
    bundle = Path(bundle).resolve()
    executable = bundle / "DesktopGremlin"
    if not executable.is_file() or executable.is_symlink() or not (bundle / "_internal").is_dir():
        raise ValueError("Missing DesktopGremlin executable or its _internal runtime folder")
    _linux_elf(executable.read_bytes()[:4096])
    if os.name == "posix" and not executable.stat().st_mode & 0o111:
        raise ValueError("DesktopGremlin is not executable")
    files = []
    for path in sorted(bundle.rglob("*")):
        relative = "DesktopGremlin/" + path.relative_to(bundle).as_posix()
        _safe_name(relative)
        if path.is_symlink():
            _link_target(relative, os.readlink(str(path)))
            try:
                target = path.resolve(strict=True)
            except (OSError, RuntimeError):
                raise ValueError("Dangling or cyclic bundle link: " + relative)
            if bundle not in target.parents or not target.is_file():
                raise ValueError("Bundle link escapes the runtime or targets a directory: " + relative)
        elif path.is_dir():
            continue
        elif not path.is_file():
            raise ValueError("Bundle contains an unsupported filesystem object: " + relative)
        files.append(path)
    _required_runtime(path.relative_to(bundle).as_posix() for path in files)
    return files


def validate_smoke_report(report, expected_version=None):
    if not isinstance(report, dict) or report.get("ok") is not True:
        raise ValueError("Packaged Linux self-test did not pass")
    if report.get("frozen") is not True or report.get("native_enabled") is not False or report.get("renderer") != "x11":
        raise ValueError("Self-test did not prove the frozen Linux X11 application")
    modules = report.get("modules", [])
    if not isinstance(modules, (list, dict)) or not MODULES.issubset(set(modules)):
        raise ValueError("Packaged self-test did not load every Linux application module")
    for key, required in (("checks", SMOKE_CHECKS), ("desktop_checks", DESKTOP_CHECKS)):
        checks = report.get(key)
        if not isinstance(checks, dict) or not required.issubset(checks) or any(value is not True for value in checks.values()):
            raise ValueError("Missing or failed Linux self-test checks: " + key)
    if expected_version is not None and report.get("version") != expected_version:
        raise ValueError("Packaged executable version does not match the release version")
    return report


def smoke(bundle, report_path, timeout=90, expected_version=None):
    if os.name != "posix" or os.environ.get("GREMLIN_ISOLATED_X11") != "1":
        raise RuntimeError("Linux smoke tests require a dedicated Xvfb display and GREMLIN_ISOLATED_X11=1")
    bundle, report_path = Path(bundle).resolve(), Path(report_path).resolve()
    validate_bundle(bundle)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if report_path.exists():
        report_path.unlink()
    env = os.environ.copy()
    for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"):
        env.pop(key, None)
    # The executable and child probes must use the bundled interpreter. Retain
    # DISPLAY/XAUTHORITY so only the explicitly isolated X server receives input.
    env["PATH"] = "/nonexistent"
    with tempfile.TemporaryDirectory(prefix="clean linux launch ", dir=str(report_path.parent)) as working:
        env["HOME"] = working
        for key, directory in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                               ("XDG_STATE_HOME", "state"), ("XDG_CACHE_HOME", "cache"),
                               ("XDG_RUNTIME_DIR", "run")):
            target = Path(working) / directory
            target.mkdir(mode=0o700)
            env[key] = str(target)
        process = subprocess.run([str(bundle / "DesktopGremlin"), "--self-test", str(report_path)],
                                 cwd=working, env=env, timeout=timeout, check=False)
    if process.returncode != 0:
        raise RuntimeError("Packaged Linux self-test exited %s; see %s" % (process.returncode, report_path))
    if not report_path.is_file():
        raise RuntimeError("Packaged Linux self-test produced no report")
    return validate_smoke_report(json.loads(report_path.read_text(encoding="utf-8")), expected_version)


def package(bundle, output, version, guide, license_path):
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?", version):
        raise ValueError("Version must be a numeric release version")
    bundle, output = Path(bundle).resolve(), Path(output).resolve()
    files = validate_bundle(bundle)
    if output == bundle or bundle in output.parents:
        raise ValueError("Release output must be outside the application bundle")
    reserved = {"README-FIRST.txt", "LICENSE.txt"}
    if any(path.relative_to(bundle).as_posix() in reserved for path in files):
        raise ValueError("Bundle already contains a reserved release document")
    output.mkdir(parents=True, exist_ok=True)
    stem = "DesktopGremlin-%s-Linux-x64" % version
    archive_path = output / (stem + ".tar.gz")
    manifest = {"version": version, "platform": "Linux-x64", "desktop": "X11",
                "glibc_minimum": "2.35", "files": []}
    documents = [(Path(guide), "README-FIRST.txt"), (Path(license_path), "LICENSE.txt")]
    sources = [(path, path.relative_to(bundle).as_posix()) for path in files] + documents
    with tarfile.open(archive_path, "w:gz", format=tarfile.PAX_FORMAT, dereference=False) as archive:
        for path, relative in sources:
            name = "DesktopGremlin/" + relative
            entry = archive.gettarinfo(str(path), arcname=name)
            entry.uid = entry.gid = 0
            entry.uname = entry.gname = ""
            entry.mode = 0o777 if entry.issym() else (0o755 if relative == "DesktopGremlin" or path.stat().st_mode & 0o111 else 0o644)
            record = {"path": name, "bytes": entry.size, "mode": oct(entry.mode)}
            if entry.issym():
                record["link"] = entry.linkname
                archive.addfile(entry)
            else:
                record["sha256"] = digest(path)
                with open(path, "rb") as stream:
                    archive.addfile(entry, stream)
            manifest["files"].append(record)
    checksum_path = output / (stem + ".sha256")
    checksum_path.write_text(digest(archive_path) + "  " + archive_path.name + "\n", encoding="ascii")
    manifest_path = output / (stem + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    verify_archive(archive_path, checksum_path)
    return {"archive": str(archive_path), "checksum": str(checksum_path), "manifest": str(manifest_path)}


def verify_archive(archive_path, checksum_path=None):
    archive_path = Path(archive_path)
    if checksum_path:
        expected = Path(checksum_path).read_text(encoding="ascii").strip().split()
        if len(expected) != 2 or expected[1] != archive_path.name or expected[0] != digest(archive_path):
            raise ValueError("Release archive checksum does not match")
    with tarfile.open(archive_path, "r:gz") as archive:
        seen, links, total = {}, {}, 0
        for entry in archive:
            _safe_name(entry.name)
            if entry.name in seen:
                raise ValueError("Duplicate Linux archive path: " + entry.name)
            if not (entry.isfile() or entry.issym()):
                raise ValueError("Unsupported archive entry type: " + entry.name)
            seen[entry.name] = entry
            if entry.issym():
                links[entry.name] = _link_target(entry.name, entry.linkname)
            else:
                total += entry.size
        for name, target in links.items():
            visited = {name}
            while target in links:
                if target in visited:
                    raise ValueError("Cyclic archive link: " + name)
                visited.add(target)
                target = links[target]
            if target not in seen or not seen[target].isfile():
                raise ValueError("Dangling archive link: " + name)
        executable = seen.get("DesktopGremlin/DesktopGremlin")
        if executable is None or not executable.isfile() or not executable.mode & 0o111:
            raise ValueError("Archive has no runnable DesktopGremlin executable")
        with archive.extractfile(executable) as stream:
            _linux_elf(stream.read(4096))
        _required_runtime(seen)
    return {"files": len(seen), "bytes": total, "sha256": digest(archive_path)}


def x11_binaries():
    """ctypes-only dependencies are invisible to normal PyInstaller scanning."""
    if os.name != "posix":
        raise RuntimeError("Collect the Linux runtime on Linux")
    result = []
    for soname in X11_LIBRARIES:
        candidates = [Path("/usr/lib/x86_64-linux-gnu") / soname, Path("/lib/x86_64-linux-gnu") / soname]
        candidate = next((path for path in candidates if path.is_file()), None)
        if candidate is None:
            raise RuntimeError("Install the Linux build dependency providing " + soname)
        # Keep the SONAME basename; ctypes loads it from the bundled loader path.
        result.append((str(candidate), "."))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    packed = commands.add_parser("package")
    for name in ("bundle", "output", "version", "guide", "license"):
        packed.add_argument("--" + name, required=True)
    checked = commands.add_parser("smoke")
    for name in ("bundle", "report", "version"):
        checked.add_argument("--" + name, required=True)
    args = parser.parse_args()
    if args.command == "smoke":
        result = smoke(args.bundle, args.report, expected_version=args.version)
    else:
        result = package(args.bundle, args.output, args.version, args.guide, args.license)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
