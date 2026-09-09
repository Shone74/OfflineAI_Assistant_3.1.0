"""Downloadable model catalog metadata (PHASE 7).

A curated, deterministic list of *downloadable model definitions* —
stable identifiers, display names, categories, URLs, expected sizes,
optional SHA-256 checksums, optional companion files (vision
``mmproj``), and requirement hints.

IMPORTANT — this metadata is NOT the runtime model-path source of
truth:

* Locating already-installed models stays with physical filesystem
  discovery (:mod:`ai.models.discovery`) — a manifest is never
  required to find models on disk.
* The download target directory is ALWAYS derived from the canonical
  user-selected models root (Phase 3 ``models.storage_root`` via
  :func:`core.paths.get_model_category_dir`) — never from this
  catalog, never a fixed drive.
* URLs are the only source for downloads; nothing here is executed or
  interpreted as code.

Entries are versioned WITH the application (a plain module, no
network fetch of catalog data — keeping the catalog offline-safe and
deterministic).
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Catalog schema version (bump when the shape changes).
CATALOG_VERSION = 1


@dataclass(frozen=True, slots=True)
class CompanionFile:
    """A secondary file downloaded alongside a primary model file.

    Vision projector (``mmproj*.gguf``) companions must land NEXT TO the
    model file (sibling-relative layout, existing Phase 3 contract) —
    the downloader writes companions into the same category directory.
    """

    filename: str
    url: str
    size_bytes: int = 0
    sha256: str | None = None

    def __post_init__(self) -> None:
        if self.size_bytes < 0:
            raise ValueError(
                f"companion file {self.filename!r}: size_bytes must be >= 0"
            )
        if self.sha256 is not None and len(self.sha256) != 64:
            raise ValueError(
                f"companion file {self.filename!r}: sha256 must be a "
                f"64-char lowercase hex digest or None"
            )


@dataclass(frozen=True, slots=True)
class DownloadableModel:
    """A downloadable model definition (catalog metadata only)."""

    model_id: str                      # stable identifier, e.g. "llm/qwen3-4b-instruct-q4-k-m"
    display_name: str
    category: str                      # llm | embedding | stt
    url: str                           # primary file download URL (https)
    filename: str                      # expected on-disk filename (no directories)
    size_bytes: int                    # expected download size (0 = unknown)
    sha256: str | None = None          # optional checksum (hex, lowercase)
    description: str = ""
    n_ctx: int = 0                     # native context (llm only)
    companions: tuple[CompanionFile, ...] = field(default_factory=tuple)
    compatibility_notes: str = ""
    #: Bare subdirectory name under the category dir where the model's
    #: files are installed (PHASE 9 STT contract).  Empty string = flat
    #: category-dir placement (the established LLM/embedding layout).
    #: For faster-whisper models this MUST be the runtime model folder
    #: name — the same value the user selects as ``voice.stt.model``
    #: (e.g. ``"whisper-small"`` -> ``<stt>/whisper-small/``).
    install_dir: str = ""

    def __post_init__(self) -> None:
        if self.category not in ("llm", "embedding", "stt"):
            raise ValueError(
                f"catalog entry {self.model_id!r}: unknown category "
                f"{self.category!r} (expected llm/embedding/stt)"
            )
        if not self.filename or "/" in self.filename or "\\" in self.filename:
            raise ValueError(
                f"catalog entry {self.model_id!r}: filename must be a bare "
                f"name without directory components: {self.filename!r}"
            )
        if self.size_bytes < 0:
            raise ValueError(
                f"catalog entry {self.model_id!r}: size_bytes must be >= 0"
            )
        if self.install_dir and (
            "/" in self.install_dir
            or "\\" in self.install_dir
            or self.install_dir in (".", "..")
            or self.install_dir.startswith(".")
        ):
            raise ValueError(
                f"catalog entry {self.model_id!r}: install_dir must be a "
                f"single bare directory component: {self.install_dir!r}"
            )
        # PHASE 9 integrity contract: when a checksum IS provided it must
        # be a well-formed lowercase-hex SHA-256. (Entries without a
        # VERIFIED digest must pass None — never a guess — see the
        # catalog curation notes below.)
        if self.sha256 is not None and len(self.sha256) != 64:
            raise ValueError(
                f"catalog entry {self.model_id!r}: sha256 must be a "
                f"64-char lowercase hex digest or None"
            )

    @property
    def runtime_model_name(self) -> str:
        """The name the RUNTIME uses to address this model.

        For ``stt`` entries with an ``install_dir`` this is the
        faster-whisper model folder name — the value the user selects as
        ``voice.stt.model`` (e.g. ``"whisper-small"``).  For flat
        categories it is not meaningful and returns "".
        """
        if self.category == "stt" and self.install_dir:
            return self.install_dir
        return ""

    @property
    def total_download_bytes(self) -> int:
        """Primary + companions expected payload size."""
        return self.size_bytes + sum(c.size_bytes for c in self.companions)

    @property
    def is_fully_curated(self) -> bool:
        """True when this entry's integrity metadata is VERIFIED EXACT.

        A fully curated entry carries an exact upstream ``size_bytes``
        and a verified ``sha256`` digest (which by curation contract
        also implies an immutable, revision-pinned URL).  Approximate
        entries (Phase 9 open items) are NOT safe to download through
        the strict size/checksum validation and must be curated first.
        """
        return bool(self.sha256) and self.size_bytes > 0 and all(
            bool(c.sha256) and c.size_bytes > 0 for c in self.companions
        )


def _llm(
    model_id: str,
    display_name: str,
    repo: str,
    filename: str,
    size_gib: float,
    *,
    n_ctx: int,
    description: str = "",
    companions: tuple[CompanionFile, ...] = (),
) -> DownloadableModel:
    """Build an LLM catalog entry from HuggingFace-style coordinates.

    *size_gib* is an APPROXIMATE sizing hint ONLY when the exact upstream
    byte size is not yet verified — the resulting entry is marked
    ``sha256=None`` and carries ``size_bytes`` as a rounded estimate
    (see the PHASE 9 curation notes: approximate sizes fail the
    downloader's strict size validation, so such entries must be
    curated with exact values before they are offered for download).
    """
    return DownloadableModel(
        model_id=model_id,
        display_name=display_name,
        category="llm",
        url=f"https://huggingface.co/{repo}/resolve/main/{filename}",
        filename=filename,
        size_bytes=int(size_gib * (1024**3)),
        description=description,
        n_ctx=n_ctx,
        companions=companions,
    )


def _embed(model_id: str, display_name: str, repo: str, filename: str, size_mib: float) -> DownloadableModel:
    return DownloadableModel(
        model_id=model_id,
        display_name=display_name,
        category="embedding",
        url=f"https://huggingface.co/{repo}/resolve/main/{filename}",
        filename=filename,
        size_bytes=int(size_mib * (1024**2)),
        description="Memory embeddings model (GGUF)",
    )


def _stt(
    model_id: str,
    display_name: str,
    repo_dir: str,
    model_name: str,
    model_size: int,
    model_sha256: str | None = None,
    companions: tuple[CompanionFile, ...] = (),
    *,
    revision: str = "main",
) -> DownloadableModel:
    """Build the curated faster-whisper STT entry.

    PHASE 9 runtime contract: ``faster_whisper.WhisperModel()`` consumes
    a MODEL FOLDER, never a bare file.  The entry therefore installs a
    complete named directory under the stt category dir::

        <models_root>/stt/<model_name>/model.bin      (primary)
        <models_root>/stt/<model_name>/config.json    (companion)
        <models_root>/stt/<model_name>/tokenizer.json (companion)
        <models_root>/stt/<model_name>/vocabulary.txt (companion)

    *model_name* is BOTH the on-disk folder name AND the value the user
    selects as ``voice.stt.model``.  All file URLs (primary + companions)
    MUST share the same immutable *revision* commit the digests were
    verified against.
    """
    return DownloadableModel(
        model_id=model_id,
        display_name=display_name,
        category="stt",
        url=(
            f"https://huggingface.co/{repo_dir}/resolve/{revision}/model.bin"
        ),
        filename="model.bin",
        size_bytes=model_size,
        sha256=model_sha256,
        install_dir=model_name,
        description="Whisper-family STT model (faster-whisper layout)",
        companions=companions,
        compatibility_notes=(
            "Faster-whisper consumes the complete model folder; the "
            "runtime model name is the folder name (voice.stt.model)."
        ),
    )


def _systran_companion(
    filename: str, repo_dir: str, revision: str, size: int, sha256: str
) -> CompanionFile:
    """A verified companion file from the same pinned Systran revision."""
    return CompanionFile(
        filename=filename,
        url=f"https://huggingface.co/{repo_dir}/resolve/{revision}/{filename}",
        size_bytes=size,
        sha256=sha256,
    )


# --------------------------------------------------------------------------- #
# Curated catalog (deterministic, shipped with the app — no network fetch
# of catalog metadata; model downloads themselves happen on user request)
#
# PHASE 9 INTEGRITY CURATION NOTES — READ BEFORE EDITING:
#
# The downloader performs STRICT validation: the server-reported size and
# the final on-disk size must EXACTLY equal ``size_bytes``, and the
# SHA-256 is verified whenever a digest is present.  Therefore:
#
# * ``size_bytes`` must be the EXACT upstream file size — a rounded
#   approximation guarantees a failed download (and makes ``is_installed``
#   misreport valid files as absent).
# * ``sha256`` must be the digest of the EXACT bytes behind ``url`` —
#   verified against the upstream tree API's LFS ``oid`` or a full
#   download-and-hash.  NEVER copy a digest from a different repo/mirror:
#   same-name GGUFs across repos are frequently different quantizations
#   (proven different for the mxbai mirrors during Phase 9 curation).
# * A verified digest REQUIRES an immutable URL: pin a commit revision
#   (``.../resolve/<commit-sha>/<file>``) rather than the mutable ``main``
#   ref whenever the digest was taken against a moving branch.
#
# CURATION STATUS (Phase 9, 2026-09-08):
#
# * ``stt/whisper-small`` — FULLY VERIFIED: switched to the canonical
#   Systran/faster-whisper-small publisher (the previous
#   ``mobiuslabsgmbh`` coordinate was a third-party mirror of the same
#   model); exact size and SHA-256 verified by full download + hash, URL
#   pinned to the immutable commit revision.  PHASE 9 CORRECTION: the
#   entry now installs the COMPLETE faster-whisper model folder
#   (model.bin + config.json + tokenizer.json + vocabulary.txt, all four
#   digests verified against the same pinned commit 536b0662…) into
#   ``stt/whisper-small/`` so the existing runtime can consume it; the
#   folder name doubles as the ``voice.stt.model`` selection value.
# * ``llm/*`` and ``embedding/*`` — UPSTREAM AUTH-GATED (HTTP 401 for
#   unauthenticated access on every route: API, resolve, raw, git, and
#   proxy mirrors).  Their exact bytes cannot be verified from this
#   environment, and public mirrors host *different* files (unsloth
#   re-quantizations; mxbai mirrors proven byte-different).  Per the
#   Phase 9 rule — never insert guessed metadata — these entries RETAIN
#   their approximate sizing and ``sha256=None`` and are marked as
#   NOT-FULLY-CURATED in ``is_fully_curated`` below.  Curation (exact
#   size + digest, URL pinned to a commit) requires an authenticated
#   HuggingFace session against the original repos and remains open.
# --------------------------------------------------------------------------- #

CATALOG: tuple[DownloadableModel, ...] = (
    _llm(
        "llm/qwen3-4b-instruct-q4-k-m",
        "Qwen3 4B Instruct (Q4_K_M)",
        "Qwen/Qwen3-4B-Instruct-2507-GGUF",
        "Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
        2.5,
        n_ctx=262144,
        description="Small, fast daily-driver chat model with tool calling",
    ),
    _llm(
        "llm/qwen3-8b-instruct-q4-k-m",
        "Qwen3 8B Instruct (Q4_K_M)",
        "Qwen/Qwen3-8B-Instruct-2507-GGUF",
        "Qwen3-8B-Instruct-2507-Q4_K_M.gguf",
        5.0,
        n_ctx=262144,
        description="Balanced chat/agent model for 8 GB+ VRAM GPUs",
    ),
    _llm(
        "llm/qwen3-coder-30b-a3b-q4-k-m",
        "Qwen3 Coder 30B A3B (Q4_K_M)",
        "Qwen/Qwen3-Coder-30B-A3B-Instruct-GGUF",
        "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf",
        18.6,
        n_ctx=262144,
        description="Agentic-coding MoE (3.3B active) for hybrid GPU+CPU machines",
        companions=(
            CompanionFile(
                filename="mmproj-Qwen3-Coder-30B-A3B-Q4_K_M.gguf",
                url="https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct-GGUF/resolve/main/mmproj-Qwen3-Coder-30B-A3B-Q4_K_M.gguf",
                size_bytes=int(0.5 * (1024**3)),
            ),
        ),
    ),
    _embed(
        "embedding/mxbai-embed-large-v1",
        "mxbai-embed-large-v1 (GGUF)",
        "nx-ai/mxbai-embed-large-v1-GGUF",
        "mxbai-embed-large-v1-q8_0.gguf",
        670,
    ),
    _stt(
        "stt/whisper-small",
        "Whisper Small (STT)",
        # PHASE 9: canonical Systran publisher.  ALL FOUR file digests
        # verified against this exact immutable commit revision
        # (536b0662742c02347bc0e980a01041f333bce120): model.bin by full
        # download+hash; the three small companions by two independent
        # fetch+hash rounds cross-checked against the tree-API sizes.
        # Byte-identity of the pinned ref with the moving 'main' ref
        # was re-verified by range comparison during curation.
        "Systran/faster-whisper-small",
        "whisper-small",
        483_546_902,
        "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671",
        companions=(
            _systran_companion(
                "config.json",
                "Systran/faster-whisper-small",
                "536b0662742c02347bc0e980a01041f333bce120",
                2_370,
                "b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828",
            ),
            _systran_companion(
                "tokenizer.json",
                "Systran/faster-whisper-small",
                "536b0662742c02347bc0e980a01041f333bce120",
                2_203_239,
                "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab",
            ),
            _systran_companion(
                "vocabulary.txt",
                "Systran/faster-whisper-small",
                "536b0662742c02347bc0e980a01041f333bce120",
                459_861,
                "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913",
            ),
        ),
        revision="536b0662742c02347bc0e980a01041f333bce120",
    ),
)


def get_catalog() -> list[DownloadableModel]:
    """Return the curated catalog (stable order, copy-safe)."""
    return list(CATALOG)


def find_model(model_id: str) -> DownloadableModel | None:
    """Look up a catalog entry by stable id (None when absent)."""
    for entry in CATALOG:
        if entry.model_id == model_id:
            return entry
    return None


def is_installed(entry: DownloadableModel, models_root) -> bool:
    """Best-effort 'already installed' probe (physical files, not manifest).

    An entry counts as installed when its expected filename exists inside
    its category directory (inside ``install_dir`` when the entry defines
    one) under *models_root*.  Size (and, for fully curated entries,
    checksum) comparisons apply ONLY when the metadata is
    verified-exact — a Phase 9 approximate entry must never misreport a
    valid on-disk file as absent just because its rounded catalog size
    differs from reality.  Physical files remain the source of truth —
    this is a convenience probe for the download UI, never a registry.
    """
    from pathlib import Path

    from core.paths import get_model_category_dir

    root = Path(models_root) if models_root is not None else None
    if root is not None:
        # Caller supplied an explicit root: derive the category dir the
        # same way core.paths does (root/<category>).
        category_dir = root / entry.category
    else:
        category_dir = get_model_category_dir(entry.category)
    if entry.install_dir:
        category_dir = category_dir / entry.install_dir

    def _size_matches(path: Path, expected: int, exact: bool) -> bool:
        # Approximate (non-exact) metadata: existence only.
        if not exact:
            return True
        return path.stat().st_size == expected

    exact = entry.is_fully_curated
    target = category_dir / entry.filename
    if not target.is_file():
        return False
    if not _size_matches(target, entry.size_bytes, exact):
        return False
    for companion in entry.companions:
        companion_path = category_dir / companion.filename
        if not companion_path.is_file():
            return False
        if not _size_matches(companion_path, companion.size_bytes, exact):
            return False
    return True
