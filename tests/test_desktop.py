"""Opening files/folders on the host from the frozen (PyInstaller/AppImage)
build must not leak the bundle's library environment into the host handler:
xdg-open on KDE launches kde-open (a Qt app), which crashes if it loads the
bundled Qt via LD_LIBRARY_PATH."""

import json
import os
import stat
import time

from tclauncher.desktop import clean_child_env, open_path


def test_clean_child_env_restores_pyinstaller_original():
    env = {
        "PATH": "/usr/bin",
        "LD_LIBRARY_PATH": "/tmp/_MEIxyz/_internal",
        "LD_LIBRARY_PATH_ORIG": "/opt/custom/lib",
        "QT_PLUGIN_PATH": "/tmp/_MEIxyz/_internal/PySide6/plugins",
        "QT_QPA_PLATFORM_PLUGIN_PATH": "/tmp/_MEIxyz/_internal/PySide6/plugins/platforms",
    }
    cleaned = clean_child_env(env)
    assert cleaned["LD_LIBRARY_PATH"] == "/opt/custom/lib"
    assert "LD_LIBRARY_PATH_ORIG" not in cleaned
    assert "QT_PLUGIN_PATH" not in cleaned
    assert "QT_QPA_PLATFORM_PLUGIN_PATH" not in cleaned
    assert cleaned["PATH"] == "/usr/bin"


def test_clean_child_env_drops_ld_library_path_without_original():
    cleaned = clean_child_env({"PATH": "/usr/bin", "LD_LIBRARY_PATH": "/tmp/_MEIxyz"})
    assert "LD_LIBRARY_PATH" not in cleaned
    assert cleaned["PATH"] == "/usr/bin"


def test_open_path_spawns_xdg_open_with_clean_env(tmp_path, monkeypatch):
    record = tmp_path / "record.json"
    fake = tmp_path / "xdg-open"
    fake.write_text(
        "#!/bin/sh\n"
        f"python3 -c 'import json,os,sys; json.dump({{\"argv\": sys.argv[1:], "
        f"\"env\": dict(os.environ)}}, open(\"{record}\", \"w\"))' \"$@\"\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEIxyz/_internal")

    assert open_path(str(tmp_path)) is True

    for _ in range(50):
        if record.exists() and record.read_text().strip():
            break
        time.sleep(0.1)
    data = json.loads(record.read_text())
    assert data["argv"] == [str(tmp_path)]
    assert "LD_LIBRARY_PATH" not in data["env"]


def test_open_path_returns_false_without_xdg_open(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))  # empty dir: no xdg-open
    assert open_path(str(tmp_path)) is False
