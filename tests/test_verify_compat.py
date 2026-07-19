"""Verify byte-compatibility of our hashing with prospect-og's FileVerifier.

Loads the original launcher.py far enough to extract its FileVerifier class
(without importing its Windows-only GUI dependencies) and compares digests
over the same fixture tree.
"""

import ast
import sys
import types
from pathlib import Path

import pytest

from tclauncher import verify

# Sibling checkout next to this repo (see CLAUDE.md); absent on CI runners.
PROSPECT_OG_LAUNCHER = (
    Path(__file__).resolve().parents[2] / "prospect-og" / "launcher" / "launcher.py"
)

requires_prospect_og = pytest.mark.skipif(
    not PROSPECT_OG_LAUNCHER.exists(),
    reason="prospect-og sibling repo not present (hash-compat reference)",
)


def load_og_file_verifier():
    """Extract only the FileVerifier class from the original launcher source."""
    source = PROSPECT_OG_LAUNCHER.read_text()
    tree = ast.parse(source)
    nodes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "FileVerifier"]
    assert nodes, "FileVerifier not found in original launcher"
    module = types.ModuleType("og_verifier")
    module.__dict__["xxh128"] = __import__("xxhash").xxh128
    module.__dict__["Path"] = Path
    module.__dict__["Callable"] = object
    module.__dict__["logger"] = types.SimpleNamespace(exception=lambda e: None, error=lambda m: None)
    code = compile(ast.Module(body=nodes, type_ignores=[]), str(PROSPECT_OG_LAUNCHER), "exec")
    exec(code, module.__dict__)
    return module.FileVerifier


@pytest.fixture
def fixture_tree(tmp_path):
    (tmp_path / "Prospect" / "Content" / "Paks").mkdir(parents=True)
    (tmp_path / "Prospect" / "Content" / "Paks" / "mod_a.pak").write_bytes(b"A" * 1000)
    (tmp_path / "Prospect" / "Content" / "Paks" / "Mod_B.pak").write_bytes(b"B" * 5000)
    (tmp_path / "Engine").mkdir()
    (tmp_path / "Engine" / "data.bin").write_bytes(bytes(range(256)) * 100)
    (tmp_path / "crash.dmp").write_bytes(b"ignored")
    (tmp_path / "mods.json").write_text("{}")
    return tmp_path


@requires_prospect_og
def test_tree_hash_matches_original(fixture_tree):
    og = load_og_file_verifier()

    ignore_paths = {Path("mods.json")}
    og_paths = og.collect_file_paths(fixture_tree, verify.DEFAULT_IGNORED_EXTS, ignore_paths)
    our_paths = verify.collect_file_paths(fixture_tree, verify.DEFAULT_IGNORED_EXTS, ignore_paths)
    assert [str(p) for p in og_paths] == [str(p) for p in our_paths]

    og_hash = og.get_files_xxh128(fixture_tree, og_paths, None)
    our_hash = verify.get_files_xxh128(fixture_tree, our_paths, None)
    assert og_hash == our_hash


@requires_prospect_og
def test_relative_paths_hash_like_mod_integrity(fixture_tree):
    """Mod integrity hashing passes relative paths, as ModManager does."""
    og = load_og_file_verifier()
    rel_paths = [Path("Prospect/Content/Paks/mod_a.pak"), Path("Prospect/Content/Paks/Mod_B.pak")]
    assert og.get_files_xxh128(fixture_tree, rel_paths, None) == verify.get_files_xxh128(fixture_tree, rel_paths, None)


@requires_prospect_og
def test_single_file_hash_matches(fixture_tree):
    og = load_og_file_verifier()
    target = fixture_tree / "Engine" / "data.bin"
    assert og.get_file_xxh128(target) == verify.get_file_xxh128(target)


def test_ignored_files_are_excluded(fixture_tree):
    paths = verify.collect_file_paths(fixture_tree, verify.DEFAULT_IGNORED_EXTS, {Path("mods.json")})
    names = {p.name for p in paths}
    assert "crash.dmp" not in names
    assert "mods.json" not in names
    assert "mod_a.pak" in names
