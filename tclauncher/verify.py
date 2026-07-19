"""File integrity hashing, byte-compatible with prospect-og's FileVerifier.

Servers publish mod `integrity` values computed by the original launcher, so
the traversal order (case-insensitive path sort), the hashed bytes (posix
relative path, then file contents) and the algorithm (xxh128) must all match.
"""

import logging
from pathlib import Path
from typing import Callable

from xxhash import xxh128

logger = logging.getLogger(__name__)

DEFAULT_IGNORED_EXTS = {"dmp", "log", "mp4"}
DEFAULT_IGNORED_PATHS = {
    Path("launcher.exe"),
    Path("mods.json"),
    Path("Prospect/Binaries/Win64/steam_appid.txt"),
}

_BUFFER = memoryview(bytearray(1024 * 1024 * 4))  # 4MB


def collect_file_paths(dir_path: Path, ignore_extensions: set[str], ignore_paths: set[Path]) -> list[Path]:
    """Pre-scan directory tree to collect relevant paths (non-ignored files)."""
    all_paths = []
    for path in sorted(dir_path.rglob("*"), key=lambda p: str(p).lower()):
        rel_path = path.relative_to(dir_path)
        if (
            path.is_file()
            and path.suffix.lstrip(".") not in ignore_extensions
            and rel_path not in ignore_paths
        ):
            all_paths.append(path)
    return all_paths


def _hash_file(file_path: Path, h: xxh128) -> xxh128:
    try:
        with open(file_path, "rb", buffering=0) as f:
            while n := f.readinto(_BUFFER):
                h.update(_BUFFER[:n])
    except Exception as e:
        # Unreadable files contribute only their path to the digest, matching
        # the original launcher's behavior.
        logger.exception(e)
    return h


def _hash_paths(base_dir: Path, all_paths: list[Path], h: xxh128, on_progress_update: Callable | None) -> xxh128:
    if on_progress_update is None:
        on_progress_update = lambda _: None
    for path in all_paths:
        if not path.is_absolute():
            # Concat relative path and resolve to avoid traversal attack
            path = (base_dir / path).resolve()
        try:
            relative_path = path.relative_to(base_dir)
        except ValueError:
            logger.error(f"Invalid relative path to base dir: {path}")
            return h
        h.update(relative_path.as_posix().encode())
        h = _hash_file(path, h)
        on_progress_update(1)
    return h


def get_file_xxh128(file_path: Path | str) -> str:
    return _hash_file(Path(file_path), xxh128()).hexdigest()


def get_files_xxh128(base_dir: Path, all_paths: list[Path], on_progress_update: Callable | None = None) -> str:
    return _hash_paths(base_dir, all_paths, xxh128(), on_progress_update).hexdigest()
