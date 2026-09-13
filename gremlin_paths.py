"""Keep packaged assets separate from per-user settings and recovery data."""
import os
import sys


def runtime_paths(source_file, frozen=None, local_app_data=None):
    resource = os.path.dirname(os.path.abspath(source_file))
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if sys.platform == "linux":
        base = os.environ.get("XDG_DATA_HOME", "")
        if not os.path.isabs(base):
            base = os.path.join(os.path.expanduser("~"), ".local", "share")
        return resource, os.path.join(base, "DesktopGremlin")
    if not frozen:
        return resource, resource
    base = local_app_data or os.environ.get("LOCALAPPDATA")
    if not base:
        base = os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return resource, os.path.join(base, "DesktopGremlin")


def startup_command(script_path, interpreter):
    if getattr(sys, "frozen", False):
        return '"%s"' % interpreter
    return '"%s" "%s"' % (interpreter, script_path)
