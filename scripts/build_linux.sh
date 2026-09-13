#!/usr/bin/env bash
# Build/test only on a dedicated X11 display; never inject test input on a user's desktop.
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python_cmd="$project_root/.venv-linux/bin/python"
skip_install=0
skip_tests=0
while (($#)); do
    case "$1" in
        --python) python_cmd="$2"; shift 2 ;;
        --skip-install) skip_install=1; shift ;;
        --skip-tests) skip_tests=1; shift ;;
        *) printf 'Unknown argument: %s\n' "$1" >&2; exit 2 ;;
    esac
done
if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
    printf '%s\n' 'Build the Linux x64 download on Linux x86_64.' >&2
    exit 2
fi
if [[ "${GREMLIN_ISOLATED_X11:-}" != "1" || -z "${DISPLAY:-}" ]]; then
    printf '%s\n' 'Run this build under a dedicated Xvfb + window-manager display with GREMLIN_ISOLATED_X11=1.' >&2
    exit 2
fi
cd -- "$project_root"
mkdir -p build/linux dist/linux release
export PYINSTALLER_CONFIG_DIR="$project_root/build/linux/cache"
export PYTHONDONTWRITEBYTECODE=1
export XDG_SESSION_TYPE=x11
unset WAYLAND_DISPLAY

"$python_cmd" -c 'import sys, platform, struct, tkinter; assert sys.platform == "linux" and struct.calcsize("P") == 8; assert platform.libc_ver()[0] == "glibc" and tuple(map(int, platform.libc_ver()[1].split("."))) <= (2, 35), "Build on Ubuntu 22.04 or an older glibc baseline"; print(sys.version)'
if (( ! skip_install )); then
    "$python_cmd" -m pip install --disable-pip-version-check -r requirements-build-linux.txt
fi
release_version="$("$python_cmd" -c 'import re; from pathlib import Path; print(re.search(r"^VERSION = \"([^\"]+)\"$", Path("desktop_gremlin.py").read_text(encoding="utf-8"), re.M).group(1))')"
if [[ "${GITHUB_REF_TYPE:-}" == "tag" && "${GITHUB_REF_NAME:-}" != "v$release_version" ]]; then
    printf 'Release tag must match source VERSION: v%s\n' "$release_version" >&2
    exit 2
fi
if (( ! skip_tests )); then
    "$python_cmd" -B tests/run_all.py
fi
"$python_cmd" -B desktop_gremlin.py --self-test "$project_root/build/linux/source-self-test.json"
"$python_cmd" -m PyInstaller --noconfirm --clean --workpath build/linux --distpath dist/linux DesktopGremlinLinux.spec
"$python_cmd" -c 'from pathlib import Path; import re; warning = Path("build/linux/DesktopGremlinLinux/warn-DesktopGremlinLinux.txt").read_text(); missing = re.findall(r"^missing module named gremlin_.*", warning, re.M); assert not missing, "Missing application modules: " + str(missing)'
"$python_cmd" -B packaging/linux_release.py smoke --bundle dist/linux/DesktopGremlin --report build/linux/packaged-self-test.json --version "$release_version"
"$python_cmd" -B packaging/linux_release.py package --bundle dist/linux/DesktopGremlin --output release --version "$release_version" --guide USER_DOWNLOAD_LINUX.md --license LICENSE
printf 'Ready: %s/release/DesktopGremlin-%s-Linux-x64.tar.gz\n' "$project_root" "$release_version"
