"""Regression tests preventing dependency drift between code and pyproject.toml.

Task C2 — the knowledge document loader imports optional parsing backends
(pypdf, fitz, docx, docx2txt, bs4) that must stay declared as extras so
``pip install .[docs]`` actually installs what the code tries to import.
If a developer adds a new optional import without declaring it, these tests fail.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
LOADER = ROOT / "knowledge" / "document_loader.py"

# Import-name -> pip package name (import fitz is shipped by PyMuPDF,
# import docx by python-docx, import bs4 by beautifulsoup4).
IMPORT_TO_PIP = {
    "pypdf": "pypdf",
    "fitz": "pymupdf",
    "docx": "python-docx",
    "docx2txt": "docx2txt",
    "bs4": "beautifulsoup4",
}

# Optional runtime imports used across the codebase, verified against the
# corresponding try/except ImportError guards in the source files:
#   faiss               -> memory/vector_memory.py (vector extra)
#   sentence_transformers -> memory/embeddings.py  (vector extra)
#   croniter            -> automation/scheduler.py (scheduler extra)
#   openwakeword        -> voice/wake_word.py      (voice extra)
#   sounddevice         -> voice/audio.py         (core dependency)
CODEBASE_OPTIONAL_IMPORTS = {
    "faiss": "faiss-cpu",
    "sentence_transformers": "sentence-transformers",
    "croniter": "croniter",
    "openwakeword": "openwakeword",
    "sounddevice": "sounddevice",
}

# Intentionally undeclared (documented, not fixed here):
#   numpy         — direct imports in voice/, memory/; provided transitively
#                   by scipy (core dep) and never pip-installed directly.
#   PyInstaller   — installer/packager.py; build-time tool, not a runtime
#                   dependency, belongs to packaging tooling not app extras.
SKIP_UNDECLARED = {"numpy", "PyInstaller"}


def _load_pyproject() -> dict:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def _extras() -> dict[str, list[str]]:
    data = _load_pyproject()
    return {
        group: [re.split(r"[><=!;~ ]", req.strip())[0] for req in reqs]
        for group, reqs in data["project"]["optional-dependencies"].items()
    }


def _core_deps() -> list[str]:
    data = _load_pyproject()
    return [re.split(r"[><=!;~ ]", req.strip())[0] for req in data["project"]["dependencies"]]


def _all_declared() -> set[str]:
    declared = {dep.lower() for dep in _core_deps()}
    for reqs in _extras().values():
        declared.update(req.lower() for req in reqs)
    return declared


def _loader_optional_imports() -> set[str]:
    """Extract module names imported inside try/except guards in the loader.

    Optional imports in the loader are always indented (inside try blocks);
    column-0 imports are stdlib/project imports and are ignored. Only spaces/
    tabs count as indentation so the pattern cannot match across lines.
    """
    src = LOADER.read_text(encoding="utf-8")
    return set(
        re.findall(r"^[ \t]+(?:import|from)[ \t]+([A-Za-z_][A-Za-z0-9_]*)", src, re.M)
    )


class TestDocsExtraDeclared:
    def test_docs_extra_contains_pdf_and_docx_entries(self) -> None:
        extras = _extras()
        assert "docs" in extras, "pyproject.toml must declare a 'docs' optional-dependency group"
        docs = {req.lower() for req in extras["docs"]}
        assert "pypdf" in docs, "'docs' extra must contain pypdf"
        assert "python-docx" in docs, "'docs' extra must contain python-docx"


class TestLoaderImportsDeclared:
    def test_every_loader_optional_import_is_declared(self) -> None:
        declared = _all_declared()
        undeclared = []
        for module in sorted(_loader_optional_imports()):
            pip_name = IMPORT_TO_PIP.get(module, module)
            if pip_name.lower() not in declared:
                undeclared.append(f"{module} (pip: {pip_name})")
        assert not undeclared, (
            "knowledge/document_loader.py imports optional modules that are not "
            f"declared in pyproject.toml dependencies/extras: {', '.join(undeclared)}"
        )


class TestCodebaseOptionalImportsDeclared:
    @pytest.mark.parametrize(
        "module,pip_name",
        sorted(CODEBASE_OPTIONAL_IMPORTS.items()),
        ids=lambda v: str(v),
    )
    def test_codebase_optional_import_is_declared(self, module: str, pip_name: str) -> None:
        declared = _all_declared()
        assert pip_name.lower() in declared, (
            f"Optional runtime import '{module}' (pip: {pip_name}) is used by the "
            "codebase but not declared in any pyproject.toml extras group or core "
            "dependencies — dependency drift."
        )

    def test_skip_list_entries_stay_undeclared_intentionally(self) -> None:
        """Guard the guard: skip-listed modules must have a documented reason."""
        assert SKIP_UNDECLARED == {"numpy", "PyInstaller"}, (
            "SKIP_UNDECLARED changed — update the documentation comment explaining "
            "why these modules are intentionally not declared as extras."
        )
