"""Release archives reject personal files, malformed bundles and tampering.

These checks exercise real filesystem/ZIP operations. The synthetic PE fixture
tests header validation only; actual executable startup is a separate build gate.
"""
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness

gm = harness.load("packaging")
ROOT = Path(harness.ROOT)
source = ROOT / "packaging" / "release.py"
assert source.is_file(), "release packaging implementation is missing"
spec = importlib.util.spec_from_file_location("gremlin_release", str(source))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
bad = []


def synthetic_bundle(base):
    bundle = base / "DesktopGremlin"
    internal = bundle / "_internal"
    internal.mkdir(parents=True)
    pe = bytearray(300)
    pe[0:2] = b"MZ"
    struct.pack_into("<I", pe, 60, 128)
    pe[128:132] = b"PE\0\0"
    struct.pack_into("<H", pe, 132, 0x8664)
    struct.pack_into("<H", pe, 152, 0x20b)
    struct.pack_into("<H", pe, 220, 2)
    (bundle / "DesktopGremlin.exe").write_bytes(pe)
    for name in ("python314.dll", "_tkinter.pyd", "win32gui.pyd", "win32api.pyd"):
        (internal / name).write_bytes(b"synthetic test library")
    for directory, name in (("_tcl_data", "init.tcl"), ("_tk_data", "tk.tcl")):
        (internal / directory).mkdir()
        (internal / directory / name).write_text("# test resource", encoding="utf-8")
    return bundle


def expect_refusal(fn, reason):
    try:
        fn()
    except (ValueError, RuntimeError):
        return
    raise AssertionError(reason)


def check(name, fn):
    try:
        with tempfile.TemporaryDirectory(prefix="package_", dir=harness.TMP) as directory:
            fn(Path(directory))
        print("PASS " + name)
    except Exception as exc:
        bad.append(name + ": " + str(exc))
        print("FAIL " + bad[-1])


def archive_contents(base):
    bundle = synthetic_bundle(base)
    (base / "gremlin_memory.json").write_text("private sibling", encoding="utf-8")
    result = release.package(bundle, base / "output", "2.1.1", ROOT / "USER_DOWNLOAD_GUIDE.md", ROOT / "LICENSE")
    with zipfile.ZipFile(result["zip"]) as archive:
        names = archive.namelist()
        assert "DesktopGremlin/DesktopGremlin.exe" in names
        assert "DesktopGremlin/README-FIRST.txt" in names
        assert all(name.startswith("DesktopGremlin/") for name in names)
        assert not any("gremlin_memory" in name for name in names), "sibling leaked into archive"
    report = release.verify_archive(result["zip"], result["checksum"])
    assert report["files"] == len(names) and report["bytes"] > 0


def private_files(base):
    bundle = synthetic_bundle(base)
    for name in ("gremlin_settings.json", "gremlin_icon_backup.json", "gremlin_memory.json", "gremlin_log.txt"):
        private = bundle / "_internal" / name
        private.write_text("private", encoding="utf-8")
        expect_refusal(lambda: release.validate_bundle(bundle), "private runtime file was accepted: " + name)
        private.unlink()


def incomplete_bundle(base):
    bundle = synthetic_bundle(base)
    (bundle / "_internal" / "_tkinter.pyd").unlink()
    expect_refusal(lambda: release.validate_bundle(bundle), "bundle without Tk extension accepted")


def embedded_tk_resources(base):
    bundle = synthetic_bundle(base)
    (bundle / "_internal" / "_tcl_data" / "init.tcl").unlink()
    (bundle / "_internal" / "_tk_data" / "tk.tcl").unlink()
    (bundle / "_internal" / "tcl90.dll").write_bytes(b"embedded Tcl fixture")
    (bundle / "_internal" / "tcl9tk90.dll").write_bytes(b"embedded Tk fixture")
    assert release.validate_bundle(bundle), "embedded Tcl/Tk 9 layout refused"
    (bundle / "_internal" / "tcl9tk90.dll").unlink()
    expect_refusal(lambda: release.validate_bundle(bundle), "incomplete embedded Tk layout accepted")


def windowed_executable(base):
    bundle = synthetic_bundle(base)
    executable = bundle / "DesktopGremlin.exe"
    pe = bytearray(executable.read_bytes())
    struct.pack_into("<H", pe, 220, 3)
    executable.write_bytes(pe)
    expect_refusal(lambda: release.validate_bundle(bundle), "console executable accepted")


def checksum_tampering(base):
    bundle = synthetic_bundle(base)
    result = release.package(bundle, base / "output", "2.1.1", ROOT / "USER_DOWNLOAD_GUIDE.md", ROOT / "LICENSE")
    with open(result["zip"], "ab") as stream:
        stream.write(b"unexpected modification")
    expect_refusal(lambda: release.verify_archive(result["zip"], result["checksum"]), "altered archive passed checksum")


def archive_paths(base):
    archive = base / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("../gremlin_memory.json", "private")
    expect_refusal(lambda: release.verify_archive(archive), "traversal archive was accepted")
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("DesktopGremlin/DesktopGremlin.exe", "one")
        stream.writestr("DesktopGremlin/desktopgremlin.exe", "two")
    expect_refusal(lambda: release.verify_archive(archive), "Windows filename collision was accepted")


def self_test_report(base):
    valid = {"ok": True, "frozen": True, "native_enabled": False, "renderer": "tk",
             "version": "3.0.0",
             "modules": ["gremlin_renderer", "gremlin_performance", "gremlin_profiles",
                         "gremlin_arsenal", "gremlin_motion", "gremlin_social"],
             "checks": {"single_instance": True, "bundled_imports": True,
                        "owned_withdrawn_tk": True, "simulation_and_canvas": True,
                        "expansion_engines": True, "settings_roundtrip": True,
                        "memory_roundtrip": True, "hide_cleanup": True,
                        "emergency_exit_dispatch": True}}
    release.validate_smoke_report(valid)
    for changed in ({"ok": False}, {"frozen": False}, {"native_enabled": True},
                    {"renderer": "native"}, {"modules": []}, {"checks": {"tk": False}},
                    {"checks": {"tk": True}}):
        invalid = dict(valid)
        invalid.update(changed)
        expect_refusal(lambda: release.validate_smoke_report(invalid), "invalid packaged self-test accepted: " + str(changed))
    expect_refusal(lambda: release.validate_smoke_report(valid, "3.1.0"), "mismatched executable version accepted")


def tk_resource_extraction(base):
    python_root = base / "python"
    (python_root / "tcl").mkdir(parents=True)
    for archive, entry in (("libtcl9.0.4.zip", "tcl_library/init.tcl"),
                           ("libtk9.0.4.zip", "tk_library/tk.tcl")):
        with zipfile.ZipFile(python_root / "tcl" / archive, "w") as stream:
            stream.writestr(entry, "# required runtime script")
    assert hasattr(release, "tk_resources"), "Tk script resource collection is missing"
    resources = release.tk_resources(python_root, base / "stage")
    destinations = {destination: Path(source) for source, destination in resources}
    assert (destinations["_tcl_data"] / "init.tcl").read_text() == "# required runtime script"
    assert (destinations["_tk_data"] / "tk.tcl").is_file()
    with zipfile.ZipFile(python_root / "tcl" / "libtcl9.0.4.zip", "w") as stream:
        stream.writestr("tcl_library/../../outside.txt", "bad")
    expect_refusal(lambda: release.tk_resources(python_root, base / "stage"), "Tk resource escaped staging")


try:
    for name, fn in (("archive contents and checksum", archive_contents), ("private-file refusal", private_files),
                     ("required bundled runtime", incomplete_bundle), ("windowed PE", windowed_executable),
                     ("embedded Tcl/Tk 9 resources", embedded_tk_resources),
                     ("checksum tampering", checksum_tampering), ("archive path validation", archive_paths),
                     ("frozen smoke report", self_test_report), ("Tcl/Tk archive resource staging", tk_resource_extraction)):
        check(name, fn)
finally:
    harness.teardown(gm, None)
print("\n" + ("FAIL\n" + "\n".join(bad) if bad else "PASS packaging"))
sys.exit(1 if bad else 0)
