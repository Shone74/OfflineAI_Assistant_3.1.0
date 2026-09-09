"""Model download service (PHASE 7) — catalog + hardware + downloader.

One-call orchestration used by the UI workers:

    evaluate_and_download(entry, hardware)
        -> advisory recommendation (BEFORE download)
        -> secure download into the canonical models root/category
        -> physical-file verification

Architectural rules honored here:

* The download target ALWAYS comes from the canonical
  ``models.storage_root`` (via :func:`core.paths.get_model_category_dir`)
  — the service accepts no arbitrary destination.
* The catalog is metadata only; installed-model discovery stays
  physical-filesystem based (:mod:`ai.models.discovery`).
* The advisory recommendation is deterministic
  (:mod:`ai.models.recommendation`) and reuses the Phase 4 GPU
  strategy — no benchmark numbers, no invented performance claims.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ai.hardware import HardwareSnapshot
from ai.models.recommendation import (
    ModelRequirements,
    RecommendationResult,
    evaluate_model_fit,
)
from core.logger import get_logger
from installer.catalog import DownloadableModel, is_installed
from installer.downloader import (
    DownloadResult,
    SecureModelDownloader,
)

logger = get_logger("ai.download_service")


@dataclass(frozen=True, slots=True)
class CatalogEntryStatus:
    """Advisory pre-download status of one catalog entry."""

    entry: DownloadableModel
    recommendation: RecommendationResult
    installed: bool


def requirements_for(entry: DownloadableModel) -> ModelRequirements:
    """Derive the deterministic hardware requirements of an entry."""
    return ModelRequirements(
        file_size_bytes=entry.size_bytes,
        category=entry.category,
        n_ctx=entry.n_ctx if entry.category == "llm" else 0,
    )


def evaluate_entry(
    entry: DownloadableModel,
    hardware: HardwareSnapshot,
    *,
    gpu_mode: str = "auto",
) -> RecommendationResult:
    """Advisory fit evaluation for a catalog entry (no download)."""
    return evaluate_model_fit(
        requirements_for(entry),
        hardware,
        gpu_mode=gpu_mode,
        download_size_bytes=entry.total_download_bytes,
    )


def catalog_status(
    hardware: HardwareSnapshot,
    *,
    gpu_mode: str = "auto",
    models_root: Path | None = None,
) -> list[CatalogEntryStatus]:
    """Evaluate the whole curated catalog against the hardware.

    *installed* reflects the physical-file probe (``is_installed``),
    not a manifest — files remain the source of truth.
    """
    from installer.catalog import get_catalog

    statuses: list[CatalogEntryStatus] = []
    for entry in get_catalog():
        statuses.append(
            CatalogEntryStatus(
                entry=entry,
                recommendation=evaluate_entry(entry, hardware, gpu_mode=gpu_mode),
                installed=is_installed(entry, models_root),
            )
        )
    return statuses


def download_entry(
    entry: DownloadableModel,
    *,
    gpu_mode: str = "auto",
    hardware: HardwareSnapshot | None = None,
    progress_callback=None,
    validator=None,
    downloader_factory=None,
) -> tuple[DownloadResult, list[DownloadResult]]:
    """Download a catalog entry (primary + companions) into the models root.

    Returns ``(primary_result, companion_results)``.  Every file lands
    in the entry's category directory under the canonical models root;
    companions (vision ``mmproj``) land NEXT TO the model (existing
    sibling-relative contract).  Failures of companion files do not
    delete the primary; the primary result is returned first.

    *downloader_factory* (optional) lets a caller — typically the UI
    download worker — construct the :class:`SecureModelDownloader` so it
    can hold a real reference for cooperative cancellation while the
    service keeps full orchestration (curation gate, companions).  It
    must be a callable accepting the same keyword arguments the service
    passes and returning a downloader-compatible object; omitting it
    preserves the previous behavior exactly.
    """
    hw = hardware if hardware is not None else None
    if hw is not None:
        verdict = evaluate_entry(entry, hw, gpu_mode=gpu_mode)
        if verdict.verdict is not None and not verdict.is_runnable:
            from installer.downloader import DownloadResult, DownloadStatus

            return (
                DownloadResult(
                    success=False,
                    dest=Path(entry.filename),
                    size_bytes=0,
                    checksum_sha256="",
                    status=DownloadStatus.FAILED,
                    error=f"Model not recommended for this hardware: {verdict.reason}",
                ),
                [],
            )

    def _make_downloader() -> SecureModelDownloader:
        if downloader_factory is not None:
            return downloader_factory(
                category=entry.category,
                install_dir=entry.install_dir or None,
                progress_callback=progress_callback,
                validator=validator,
            )
        return SecureModelDownloader(
            category=entry.category,
            install_dir=entry.install_dir or None,
            progress_callback=progress_callback,
            validator=validator,
        )

    downloader = _make_downloader()
    # PHASE 9: only fully curated entries are downloadable.  Approximate
    # metadata (rounded sizes, no digest) would fail the downloader's
    # STRICT size equality anyway — reject up front with a clear reason
    # instead of a mid-download size-mismatch error, and never hand a
    # guessed digest to validation.
    if not entry.is_fully_curated:
        from installer.downloader import DownloadResult, DownloadStatus

        return (
            DownloadResult(
                success=False,
                dest=downloader.dest_dir / entry.filename,
                size_bytes=0,
                checksum_sha256="",
                status=DownloadStatus.FAILED,
                error=(
                    f"Catalog entry '{entry.model_id}' is not fully "
                    f"curated (exact size + SHA-256) and cannot be "
                    f"downloaded safely. See installer/catalog.py "
                    f"curation notes."
                ),
            ),
            [],
        )
    primary = downloader.download(
        url=entry.url,
        filename=entry.filename,
        expected_size=entry.size_bytes or None,
        expected_sha256=entry.sha256,
    )
    companions: list[DownloadResult] = []
    for companion in entry.companions:
        if primary.status.value == "cancelled":
            break
        if not (companion.size_bytes and companion.sha256):
            # Fully-curated entries guarantee curated companions; a
            # companion lacking verified metadata must never download.
            from installer.downloader import DownloadResult, DownloadStatus

            companions.append(
                DownloadResult(
                    success=False,
                    dest=downloader.dest_dir / companion.filename,
                    size_bytes=0,
                    checksum_sha256="",
                    status=DownloadStatus.FAILED,
                    error=(
                        f"Companion '{companion.filename}' lacks verified "
                        f"integrity metadata; download refused."
                    ),
                )
            )
            continue
        companion_result = downloader.download(
            url=companion.url,
            filename=companion.filename,
            expected_size=companion.size_bytes or None,
            expected_sha256=companion.sha256,
        )
        companions.append(companion_result)
    if primary.success:
        logger.info(
            "Catalog entry downloaded: %s (+%d companion(s))",
            entry.model_id, len(companions),
        )
    return primary, companions
