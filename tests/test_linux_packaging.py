"""Portable archive checks; real Linux ELF startup is the Linux build gate."""
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / "tests" / ".tmp"
TMP.mkdir(parents=True, exist_ok=True)
SOURCE = ROOT / "packaging" / "linux_release.py"


class LinuxPackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert SOURCE.is_file(), "Linux archive implementation is missing"
        spec = importlib.util.spec_from_file_location("linux_release", str(SOURCE))
        cls.release = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.release)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="linux_package_", dir=str(TMP))
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.bundle = self.base / "DesktopGremlin"
        internal = self.bundle / "_internal"
        internal.mkdir(parents=True)
        # Minimal synthetic ELF header validates architecture, not actual startup.
        elf = bytearray(64)
        elf[:7] = b"\x7fELF\x02\x01\x01"
        struct.pack_into("<HHI", elf, 16, 3, 62, 1)
        (self.bundle / "DesktopGremlin").write_bytes(elf)
        (self.bundle / "DesktopGremlin").chmod(0o755)
        for name in ("libpython3.10.so.1.0", "_tkinter.cpython-310-x86_64-linux-gnu.so",
                     "libX11.so.6", "libXext.so.6", "libXtst.so.6", "libXrandr.so.2", "libXss.so.1",
                     "init.tcl", "tk.tcl"):
            (internal / name).write_bytes(b"synthetic runtime")

    def package(self):
        return self.release.package(self.bundle, self.base / "out", "3.1.0",
                                    ROOT / "USER_DOWNLOAD_LINUX.md", ROOT / "LICENSE")

    def test_archive_retains_executable_and_excludes_siblings(self):
        (self.base / "gremlin_memory.json").write_text("private", encoding="utf-8")
        result = self.package()
        with tarfile.open(result["archive"], "r:gz") as archive:
            entries = {entry.name: entry for entry in archive.getmembers()}
            self.assertEqual(entries["DesktopGremlin/DesktopGremlin"].mode, 0o755)
            self.assertIn("DesktopGremlin/README-FIRST.txt", entries)
            self.assertNotIn("DesktopGremlin/gremlin_memory.json", entries)
        verified = self.release.verify_archive(result["archive"], result["checksum"])
        self.assertEqual(verified["files"], len(entries))
        self.assertGreater(verified["bytes"], 0)

    def test_private_data_and_missing_libraries_refused(self):
        private = self.bundle / "_internal" / "gremlin_settings.json"
        private.write_text("private", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.release.validate_bundle(self.bundle)
        private.unlink()
        (self.bundle / "_internal" / "libX11.so.6").unlink()
        with self.assertRaises(ValueError):
            self.release.validate_bundle(self.bundle)

    def test_non_linux_or_wrong_architecture_refused(self):
        executable = self.bundle / "DesktopGremlin"
        elf = bytearray(executable.read_bytes())
        struct.pack_into("<H", elf, 18, 183)  # AArch64 cannot be labelled x64.
        executable.write_bytes(elf)
        with self.assertRaises(ValueError):
            self.release.validate_bundle(self.bundle)
        executable.write_bytes(b"MZ" + bytes(100))
        with self.assertRaises(ValueError):
            self.release.validate_bundle(self.bundle)

    def test_archive_rejects_paths_and_escaping_links(self):
        valid = self.package()["archive"]
        path = self.base / "bad.tar.gz"
        for name, target in (("../outside", None),
                             ("DesktopGremlin/_internal/libx.so", "../../outside"),
                             ("DesktopGremlin/_internal/libx.so", "/etc/passwd")):
            with tarfile.open(path, "w:gz") as archive, tarfile.open(valid, "r:gz") as original:
                for entry in original:
                    archive.addfile(entry, original.extractfile(entry) if entry.isfile() else None)
                entry = tarfile.TarInfo(name)
                if target:
                    entry.type = tarfile.SYMTYPE
                    entry.linkname = target
                    archive.addfile(entry)
                else:
                    entry.size = 4
                    archive.addfile(entry, io.BytesIO(b"data"))
            with self.assertRaises(ValueError):
                self.release.verify_archive(path)

    def test_relative_runtime_links_preserved_but_cycles_refused(self):
        valid = self.package()["archive"]
        path = self.base / "links.tar.gz"
        for target, accepted in (("libX11.so.6", True), ("alias.so", False), ("missing.so", False)):
            with tarfile.open(path, "w:gz") as archive, tarfile.open(valid, "r:gz") as original:
                for entry in original:
                    archive.addfile(entry, original.extractfile(entry) if entry.isfile() else None)
                link = tarfile.TarInfo("DesktopGremlin/_internal/alias.so")
                link.type = tarfile.SYMTYPE
                link.linkname = target
                archive.addfile(link)
            if accepted:
                self.assertGreater(self.release.verify_archive(path)["files"], 0)
            else:
                with self.assertRaises(ValueError):
                    self.release.verify_archive(path)

    def test_checksum_detects_tampering(self):
        result = self.package()
        with open(result["archive"], "ab") as stream:
            stream.write(b"tampered")
        with self.assertRaises(ValueError):
            self.release.verify_archive(result["archive"], result["checksum"])

    def test_smoke_gate_requires_cross_process_input_evidence(self):
        valid = {"ok": True, "frozen": True, "native_enabled": False,
                 "renderer": "x11", "version": "3.1.0",
                 "modules": ["gremlin_performance", "gremlin_profiles", "gremlin_arsenal",
                             "gremlin_motion", "gremlin_social", "gremlin_linux",
                             "gremlin_x11", "gremlin_x11_overlay", "gremlin_physics", "gremlin_ragdoll"],
                 "checks": {name: True for name in ("single_instance", "bundled_imports",
                             "owned_withdrawn_tk", "simulation_and_canvas", "expansion_engines", "physics_engines",
                             "settings_roundtrip", "memory_roundtrip", "hide_cleanup", "emergency_exit_dispatch",
                             "window_tracking_and_restore")},
                 "desktop_checks": {"transparent_passthrough": True, "opaque_interaction": True,
                                    "outside_drag_release": True, "emergency_exit": True}}
        self.release.validate_smoke_report(valid, "3.1.0")
        for changed in ({"renderer": "tk"}, {"frozen": False}, {"native_enabled": True},
                        {"desktop_checks": {}}, {"modules": []}, {"checks": {}}):
            invalid = dict(valid, **changed)
            with self.assertRaises(ValueError):
                self.release.validate_smoke_report(invalid, "3.1.0")
        invalid = dict(valid, desktop_checks=dict(valid["desktop_checks"], transparent_passthrough=False))
        with self.assertRaises(ValueError):
            self.release.validate_smoke_report(invalid, "3.1.0")
        with self.assertRaises(ValueError):
            self.release.validate_smoke_report(valid, "3.2.0")
        missing_desktop = dict(valid, checks=dict(valid["checks"]))
        del missing_desktop["checks"]["window_tracking_and_restore"]
        with self.assertRaises(ValueError):
            self.release.validate_smoke_report(missing_desktop, "3.1.0")


if __name__ == "__main__":
    unittest.main()
