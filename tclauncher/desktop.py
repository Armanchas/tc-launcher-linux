"""Open files/folders with the host's default handler, safely from a frozen build.

QDesktopServices.openUrl spawns xdg-open with the *frozen* process environment:
PyInstaller points LD_LIBRARY_PATH into the bundle (and Qt adds plugin-path
vars), so a Qt-based host handler like KDE's kde-open loads the bundled Qt and
crashes ("Could not read file ..."). Spawning xdg-open ourselves with a
scrubbed environment sidesteps that.
"""

import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)

# Set by the frozen app for itself; must not leak to host helper processes.
_BUNDLE_ONLY_VARS = ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH")


def clean_child_env(env: dict[str, str]) -> dict[str, str]:
    """Environment for host child processes: undo PyInstaller's overrides.

    PyInstaller saves the pre-launch LD_LIBRARY_PATH in LD_LIBRARY_PATH_ORIG;
    restore it (or drop the override entirely) and remove Qt plugin paths that
    only make sense inside the bundle.
    """
    cleaned = dict(env)
    original = cleaned.pop("LD_LIBRARY_PATH_ORIG", None)
    if original:
        cleaned["LD_LIBRARY_PATH"] = original
    else:
        cleaned.pop("LD_LIBRARY_PATH", None)
    for var in _BUNDLE_ONLY_VARS:
        cleaned.pop(var, None)
    return cleaned


def open_path(path: str) -> bool:
    """Open a file or directory with the desktop's default handler.

    Returns False when xdg-open is unavailable so the caller can fall back
    to QDesktopServices (fine when running from source).
    """
    xdg_open = shutil.which("xdg-open")
    if xdg_open is None:
        return False
    subprocess.Popen(
        [xdg_open, path],
        env=clean_child_env(dict(os.environ)),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return True
