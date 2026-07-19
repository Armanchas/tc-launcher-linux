#!/usr/bin/env bash
# Build dist/TCLauncher-<version>-x86_64.AppImage.
# Run from the repo root. Requires: python3, network (first run downloads
# appimagetool into build/cache/).
set -euo pipefail

cd "$(dirname "$0")/.."
VENV=".venv"
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q . pyinstaller

VERSION="$("$VENV/bin/python" -c 'from tclauncher.version import APP_VERSION; print(APP_VERSION)')"
APPDIR="build/AppDir"
rm -rf build/tclauncher "$APPDIR" dist/TCLauncher-*.AppImage

# PyInstaller entry point: tclauncher/__main__.py uses package-relative imports
# ("from .config import ..."), which break when PyInstaller runs that file
# directly as the top-level __main__ module ("attempted relative import with
# no known parent package"). Build a tiny absolute-import wrapper instead,
# mirroring the console_script shim pip already generates at .venv/bin/tclauncher.
mkdir -p build
cat > build/entrypoint.py <<'ENTRYPOINT'
from tclauncher.__main__ import main

if __name__ == "__main__":
    main()
ENTRYPOINT

# 1) PyInstaller onedir bundle (onefile would double-extract inside AppImage)
"$VENV/bin/pyinstaller" --noconfirm --windowed --onedir \
    --name tclauncher \
    --distpath build \
    --workpath build/pyinstaller \
    --specpath build \
    --add-data "$(pwd)/tclauncher/assets:tclauncher/assets" \
    build/entrypoint.py

# 2) AppDir layout
mkdir -p "$APPDIR/usr/bin"
cp -r build/tclauncher/. "$APPDIR/usr/bin/"
ln -sf usr/bin/tclauncher "$APPDIR/AppRun"

cat > "$APPDIR/tclauncher.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=The Cycle Launcher
Exec=tclauncher
Icon=tclauncher
Categories=Game;
Terminal=false
DESKTOP

# 3) Icon: .ico -> 256x256 .png using the venv's own Qt (no ImageMagick dep)
"$VENV/bin/python" - "$APPDIR" <<'PY'
import sys
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QImage
app = QCoreApplication([])
img = QImage("tclauncher/assets/icon.ico")
assert not img.isNull(), "could not read tclauncher/assets/icon.ico"
img.scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(f"{sys.argv[1]}/tclauncher.png")
PY

# 4) appimagetool (cached)
mkdir -p build/cache dist
TOOL="build/cache/appimagetool-x86_64.AppImage"
if [ ! -x "$TOOL" ]; then
    curl -fsSL -o "$TOOL" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x "$TOOL"
fi

# 5) Build (--appimage-extract-and-run works without FUSE, e.g. in containers)
ARCH=x86_64 "$TOOL" --appimage-extract-and-run "$APPDIR" \
    "dist/TCLauncher-${VERSION}-x86_64.AppImage"
echo "Built dist/TCLauncher-${VERSION}-x86_64.AppImage"
