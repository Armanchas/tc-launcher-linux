"""Mod install/uninstall/integrity logic (no UI), ported from prospect-og.

Local install state lives in mods.json inside the game directory; downloaded
archives are cached under ~/.tclauncher/mods.
"""

import json
import logging
import os
from enum import Enum
from pathlib import Path
from typing import Callable, NamedTuple, TypedDict
from zipfile import ZipFile

from . import verify
from .backend import BackendClient
from .config import LAUNCHER_USERDIR, ConfigManager

logger = logging.getLogger(__name__)

MOD_FILE = "mods.json"


class ModStatus(Enum):
    NOT_INSTALLED = "Not installed"
    UPDATE_AVAILABLE = "Update available"
    CORRUPTED_INSTALLATION = "Corrupted installation"
    UP_TO_DATE = "Up-to-date"


class RemoteModManifest(TypedDict):
    id: str
    author: str
    name: str
    version: str
    hash: str        # xxh128 of the mod archive
    integrity: str   # xxh128 of all installed files
    url: str


class LocalModManifest(RemoteModManifest):
    files: list[str]


class Mod(NamedTuple):
    id: str
    local: LocalModManifest | None
    remote: RemoteModManifest
    status: ModStatus


class ModManager:
    def __init__(self, config: ConfigManager, backend: BackendClient):
        self.config = config
        self.backend = backend
        self.installed_mods: dict[str, LocalModManifest] = {}
        self.remote_mods: dict[str, RemoteModManifest] = {}
        self.cache_dir = os.path.join(LAUNCHER_USERDIR, "mods")
        os.makedirs(self.cache_dir, exist_ok=True)

    def _mod_file(self) -> str:
        return os.path.join(self.config.game_dir, MOD_FILE)

    def _read_installed_mods(self):
        try:
            with open(self._mod_file(), "r", encoding="utf-8") as f:
                self.installed_mods = json.load(f)
        except Exception as e:
            logger.exception(e)
            self.installed_mods = {}

    def _write_installed_mods(self):
        with open(self._mod_file(), "w", encoding="utf-8") as f:
            json.dump(self.installed_mods, f, indent=2)

    def load_mods(self):
        """Sync local state with the server: drop mods the server no longer lists."""
        self._read_installed_mods()
        self.remote_mods = self.backend.remote_mods()

        new_mods = {}
        for mod_id, mod in self.installed_mods.items():
            if mod_id in self.remote_mods:
                new_mods[mod_id] = mod
                continue
            self.uninstall_mod(mod)
        self.installed_mods = new_mods
        self._write_installed_mods()

    def check_mod_integrity(self, local_mod: LocalModManifest, remote_mod: RemoteModManifest) -> bool:
        paths = [Path(file) for file in local_mod["files"]]
        local_integrity = verify.get_files_xxh128(Path(self.config.game_dir), paths, None)
        return local_integrity == remote_mod["integrity"]

    def get_mods_with_statuses(self, refresh: bool = True) -> list[Mod]:
        if refresh:
            self.load_mods()

        mods: list[Mod] = []
        for mod_id, remote_mod in self.remote_mods.items():
            local_mod = self.installed_mods.get(mod_id)
            status = ModStatus.UP_TO_DATE
            if not local_mod:
                status = ModStatus.NOT_INSTALLED
            elif local_mod["version"] != remote_mod["version"]:
                status = ModStatus.UPDATE_AVAILABLE
            elif not self.check_mod_integrity(local_mod, remote_mod):
                status = ModStatus.CORRUPTED_INSTALLATION
            mods.append(Mod(mod_id, local_mod, remote_mod, status))
        return mods

    def are_mods_installed(self) -> bool:
        mods = self.get_mods_with_statuses()
        return all(mod.status == ModStatus.UP_TO_DATE for mod in mods)

    def get_mod_file_paths(self) -> set[Path]:
        paths = set()
        for mod in self.installed_mods.values():
            for file in mod["files"]:
                paths.add(Path(file))
        return paths

    def uninstall_mod(self, mod: LocalModManifest):
        for file in mod["files"]:
            filepath = os.path.join(self.config.game_dir, file)
            if os.path.exists(filepath):
                os.remove(filepath)

    def install_mod(self, mod: Mod, on_progress: Callable | None = None):
        """Install or reinstall a mod; updates mods.json. Raises on failure."""
        if mod.status != ModStatus.NOT_INSTALLED and mod.local is not None:
            self.uninstall_mod(mod.local)
        files = self._download_and_extract(mod.remote, on_progress)
        self.installed_mods[mod.id] = {**mod.remote, "files": files}
        self._write_installed_mods()

    def _download_and_extract(self, mod: RemoteModManifest, on_progress: Callable | None = None) -> list[str]:
        filename = f"{mod['id'].replace('/', '_')}_{mod['version']}.zip"
        cache_path = os.path.join(self.cache_dir, filename)

        def _cached_hash_ok(path: str, expected_hash: str) -> bool:
            h = verify.get_file_xxh128(path)
            if h != expected_hash:
                logger.warning(f"Mod hash mismatch, got: {h}, expected: {expected_hash}")
                return False
            return True

        if not os.path.exists(cache_path) or not _cached_hash_ok(cache_path, mod["hash"]):
            self.backend.download(mod["url"], cache_path, on_progress)

        with ZipFile(cache_path) as z:
            z.extractall(self.config.game_dir)
            files = [name for name in z.namelist() if not name.endswith("/")]
        return files
