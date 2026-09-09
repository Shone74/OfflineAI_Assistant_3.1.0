"""Secure model download manager (PHASE 7).

Downloads large GGUF model files into the canonical user-selected
models root with a strict safety contract:

* **Streaming only** — fixed-size chunks, never the whole file in RAM.
* **Scoped writes** — destinations are derived EXCLUSIVELY from the
  canonical models root + category resolver (:mod:`core.paths`), and
  re-validated through the existing filesystem security boundary
  (:class:`tools.file_security.PathValidator`): ``..`` traversal,
  absolute filenames, symlink/junction escapes and non-model file
  types are rejected before a single byte is fetched.
* **No falsely-complete files** — downloads write to a ``.part``
  suffix and are atomically renamed only after full validation
  (expected size when known, SHA-256 when provided).  Discovery
  ignores ``*.part`` files.
* **Safe resume** — HTTP Range-based resume is attempted ONLY when the
  server supports it AND the partial file's size matches the range
  offset; on any mismatch the download restarts cleanly rather than
  corrupting the file.  An existing VALID model file (complete size /
  checksum match) is never re-downloaded or appended to.
* **Disk-space safety** — free space on the actual models-root drive
  is checked (with safety margin) BEFORE downloading; clearly
  insufficient space fails the download without fetching bytes.
* **Clean cancellation** — cancel stops at the next chunk boundary,
  closes the file, and leaves only a ``.part`` file (never a complete
  model).  An existing valid model is never touched.
* **Checksums** — SHA-256 verified whenever provided (mandatory
  behavior when present, optional when the metadata has none); size
  validation whenever the expected size is known.  A mismatch fails
  the download and removes the corrupt ``.part`` file.
* **Never executes or interprets** downloaded content — model files
  are opaque data, only ever opened for reading/hashing.

The legacy v1 surface (``ModelDownloader``, ``DownloadResult``,
``DownloadProgress``, ``DownloadStatus``) is preserved for backward
compatibility; :class:`SecureModelDownloader` is the Phase 7 entry
point used by the application and UI.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import requests

from core.logger import get_logger

logger = get_logger("installer.downloader")

DEFAULT_CHUNK_SIZE = 1024 * 1024  # 1 MB chunks
DEFAULT_MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30  # seconds per chunk

#: Free-space head-room required beyond the download size on the
#: models drive (temp data, filesystem overhead).  Mirrors the
#: recommendation layer's margin.
DISK_SAFETY_MARGIN_BYTES = 512 * 1024 * 1024  # 512 MiB

#: Suffix for in-progress downloads — NEVER the final model name.
PART_SUFFIX = ".part"

#: Allowed on-disk model payload extensions (defense in depth: the
#: catalog is curated, but the generic filename check enforces this
#: for every caller).  ``.json``/``.txt`` are the faster-whisper model
#: FOLDER assets (config/tokenizer/vocabulary) that accompany the
#: curated STT ``model.bin`` — never standalone download targets.
_ALLOWED_SUFFIXES = {".gguf", ".bin", ".json", ".txt"}


class DownloadStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class DownloadResult:
    success: bool
    dest: Path
    size_bytes: int
    checksum_sha256: str
    status: DownloadStatus
    error: str | None = None


@dataclass
class DownloadProgress:
    bytes_downloaded: int = 0
    total_bytes: int | None = None
    chunks_downloaded: int = 0
    status: DownloadStatus = DownloadStatus.PENDING
    error: str | None = None


_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ ()+-]*$")


def _validate_model_filename(filename: str) -> str:
    """Validate a bare model filename (no directories, no traversal).

    Returns the cleaned filename or raises ``ValueError``.  Rules:

    * bare name only — no ``/``, no ``\\``, no drive letters, no ``..``
    * no null bytes, no leading dot, no invalid characters
    * must carry a known model payload extension
    """
    if not filename or not filename.strip():
        raise ValueError("Model filename must not be empty")
    name = filename.strip()
    if "\x00" in name:
        raise ValueError("Model filename contains null bytes")
    if name != name.strip() or name.startswith(".") or name.endswith("."):
        raise ValueError(f"Invalid model filename: {filename!r}")
    if "/" in name or "\\" in name:
        raise ValueError(
            f"Model filename must not contain directory components: {filename!r}"
        )
    if ".." in name or name.startswith("-"):
        raise ValueError(f"Model filename looks unsafe: {filename!r}")
    if ":" in name:  # drive letters / NTFS alternate data streams
        raise ValueError(f"Model filename must not contain ':': {filename!r}")
    if not _FILENAME_RE.match(name):
        raise ValueError(f"Model filename contains invalid characters: {filename!r}")
    suffix = Path(name).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise ValueError(
            f"Model filename must end with a model payload extension "
            f"({sorted(_ALLOWED_SUFFIXES)}): {filename!r}"
        )
    return name


def _sha256_of_file(path: Path, chunk_size: int) -> str:
    """Streamed SHA-256 of an existing file (never loads it into RAM)."""
    sha = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            sha.update(chunk)
    return sha.hexdigest()


def check_disk_space(models_root: Path, required_bytes: int) -> tuple[bool, str | None]:
    """Verify free space on the models-root drive BEFORE downloading.

    Returns ``(ok, reason)`` — *ok* is False with a human-readable
    *reason* when clearly insufficient (required + margin > free).
    Unknown free-space values pass (no invented numbers) with a
    logged warning; the runtime will surface real write failures.
    """
    if required_bytes <= 0:
        return True, None
    try:
        import psutil

        probe_dir = models_root if models_root.exists() else models_root.anchor
        free = psutil.disk_usage(str(probe_dir)).free
    except Exception as exc:
        logger.warning("Disk-space probe failed for %s: %s", models_root, exc)
        return True, None
    needed = required_bytes + DISK_SAFETY_MARGIN_BYTES
    if free < needed:
        return False, (
            f"Insufficient disk space on the models drive: "
            f"{free / (1024**3):.1f} GB free, "
            f"{needed / (1024**3):.1f} GB required (incl. safety margin)"
        )
    return True, None


def _validate_install_dir(install_dir: str) -> str:
    """Validate a bare subdirectory name under the category dir.

    PHASE 9 STT contract: faster-whisper models install into a NAMED
    subdirectory (``<stt>/<model_name>/``).  The same security rules as
    filenames apply — single path component, no traversal, no absolute
    prefixes, no drive letters — but without the extension allowlist
    (the directory is not a model payload file).
    """
    if not install_dir or not install_dir.strip():
        raise ValueError("install_dir must not be empty")
    name = install_dir.strip()
    if "\x00" in name:
        raise ValueError("install_dir contains null bytes")
    if "/" in name or "\\" in name:
        raise ValueError(
            f"install_dir must be a single directory component: {install_dir!r}"
        )
    if name in (".", "..") or ".." in name or name.startswith(".") or name.endswith("."):
        raise ValueError(f"install_dir looks unsafe: {install_dir!r}")
    if ":" in name:  # drive letters / NTFS alternate data streams
        raise ValueError(f"install_dir must not contain ':': {install_dir!r}")
    if not _FILENAME_RE.match(name):
        raise ValueError(f"install_dir contains invalid characters: {install_dir!r}")
    return name


class SecureModelDownloader:
    """Phase 7 model downloader for the canonical models root.

    Destinations are derived from the Phase 3 architecture:
    ``get_model_category_dir(category) [/ install_dir] / filename`` — the
    user-selected ``models.storage_root`` is the ONLY root; nothing here
    can direct a download to an arbitrary path.  *install_dir* (PHASE 9)
    is an optional bare subdirectory for models that the runtime
    consumes as a FOLDER (faster-whisper STT); when set, every download
    through this instance lands inside that subdirectory.
    """

    def __init__(
        self,
        category: str = "llm",
        *,
        models_root: str | Path | None = None,
        install_dir: str | None = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        progress_callback: Callable[[DownloadProgress], None] | None = None,
        validator: object | None = None,
    ) -> None:
        from core.paths import MODEL_CATEGORIES, get_model_category_dir, get_models_root

        if category not in MODEL_CATEGORIES:
            raise ValueError(
                f"Unknown model category {category!r}; expected {MODEL_CATEGORIES}"
            )
        self.category = category
        # Resolve the category dir ONCE from the canonical architecture
        # (explicit root override honored, still category-scoped).
        if models_root is not None:
            root = Path(models_root)
            if not root.is_absolute():
                raise ValueError(
                    f"models_root must be absolute; got {models_root!r}"
                )
            self.dest_dir = root / category
        else:
            self.dest_dir = get_model_category_dir(category)
        # PHASE 9: optional bare subdirectory under the category dir
        # (faster-whisper model folders).  Validated with the same
        # security rules as filenames; the resolved destination remains
        # containment-checked inside the category dir.
        self.install_dir = (
            _validate_install_dir(install_dir) if install_dir else ""
        )
        if self.install_dir:
            self.dest_dir = self.dest_dir / self.install_dir
        self._models_root = (
            Path(models_root).resolve() if models_root is not None else get_models_root()
        )
        self.chunk_size = max(64 * 1024, chunk_size)
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self._progress_callback = progress_callback
        self._cancelled = False
        self._validator = validator  # optional PathValidator injection
        logger.debug(
            "SecureModelDownloader(%s) -> %s", category, self.dest_dir
        )

    # ------------------------------------------------------------------ #
    # Security boundary
    # ------------------------------------------------------------------ #

    def _authorized_dest(self, filename: str) -> Path:
        """Validate and resolve the final destination (never arbitrary).

        Re-uses the existing filesystem security boundary when
        available (default validator, models-root-scoped), and ALWAYS
        additionally verifies: bare filename, no traversal, resolved
        destination stays inside the category directory.
        """
        name = _validate_model_filename(filename)
        dest = self.dest_dir / name

        # Primary guard: containment on the RESOLVED path (symlink/
        # junction escapes land outside the category dir and fail).
        try:
            resolved_dest = dest.resolve(strict=False)
            resolved_dir = self.dest_dir.resolve(strict=False)
            resolved_dest.relative_to(resolved_dir)
        except (ValueError, OSError):
            raise ValueError(
                f"Download destination escapes the models directory: {filename!r}"
            ) from None

        # Re-use the existing PathValidator boundary when injectable —
        # the application-wide filesystem policy stays authoritative.
        if self._validator is not None:
            try:
                self._validator.validate_write(str(dest), create_parent=False)
            except Exception as exc:
                raise ValueError(
                    f"Download destination rejected by filesystem security: {exc}"
                ) from exc
        return dest

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def cancel(self) -> None:
        """Signal cancellation at the next chunk boundary (safe)."""
        self._cancelled = True

    def download(
        self,
        url: str,
        filename: str,
        expected_size: int | None = None,
        expected_sha256: str | None = None,
    ) -> DownloadResult:
        """Download *url* to the category dir under the models root.

        * *filename* — bare model filename (validated; no directories).
        * *expected_size* — exact final size when known (validated).
        * *expected_sha256* — hex digest when provided by metadata.

        Never overwrites a valid existing model.  Writes ``<name>.part``
        and atomically renames on success only.
        """
        dest = self._authorized_dest(filename)

        # 1. Existing valid file — never re-download or append.
        existing = self._existing_valid_file(dest, expected_size, expected_sha256)
        if existing is not None:
            self._emit(DownloadProgress(
                bytes_downloaded=existing.stat().st_size,
                total_bytes=existing.stat().st_size,
                status=DownloadStatus.COMPLETED,
            ))
            return DownloadResult(
                success=True,
                dest=dest,
                size_bytes=existing.stat().st_size,
                checksum_sha256=_sha256_of_file(existing, self.chunk_size)
                if expected_sha256 else "",
                status=DownloadStatus.COMPLETED,
                error=None,
            )

        # 2. Disk-space safety BEFORE any bytes (models-root drive).
        size_for_disk = expected_size or 0
        ok, reason = check_disk_space(self._models_root, size_for_disk)
        if not ok:
            return self._fail(dest, reason, DownloadStatus.FAILED)

        # 3. Attempt loop (transient errors only; clean restarts).
        last_error: str | None = None
        for attempt in range(1, self.max_retries + 1):
            if self._cancelled:
                return self._fail(
                    dest, "Download cancelled by user", DownloadStatus.CANCELLED
                )
            try:
                return self._download_attempt(
                    url, dest, expected_size, expected_sha256
                )
            except _Cancelled:
                return self._fail(
                    dest, "Download cancelled by user", DownloadStatus.CANCELLED
                )
            except requests.RequestException as exc:
                last_error = f"Network error (attempt {attempt}): {exc}"
                logger.warning("Download attempt %d failed: %s", attempt, exc)
            except OSError as exc:
                last_error = f"File error (attempt {attempt}): {exc}"
                logger.warning("Download file error, attempt %d: %s", attempt, exc)
        return self._fail(dest, last_error or "Download failed", DownloadStatus.FAILED)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _emit(self, progress: DownloadProgress) -> None:
        if self._progress_callback is not None:
            try:
                self._progress_callback(progress)
            except Exception:
                pass

    def _fail(self, dest: Path, error: str, status: DownloadStatus) -> DownloadResult:
        if status is DownloadStatus.CANCELLED:
            logger.info("Download cancelled: %s", dest.name)
        else:
            logger.error("Download failed (%s): %s — %s", dest.name, status, error)
        return DownloadResult(
            success=False,
            dest=dest,
            size_bytes=0,
            checksum_sha256="",
            status=status,
            error=error,
        )

    def _existing_valid_file(
        self, dest: Path, expected_size: int | None, expected_sha256: str | None
    ) -> Path | None:
        """Return *dest* when a valid complete model already exists.

        A file is "valid" when its size matches *expected_size* (when
        known) and its checksum matches *expected_sha256* (when
        provided).  With neither piece of metadata, existence alone
        counts (physical files are the source of truth) — but a
        ``.part`` sibling is still not a model.
        """
        if not dest.is_file():
            return None
        size = dest.stat().st_size
        if expected_size is not None and size != expected_size:
            return None  # wrong size — treat as absent, download fresh
        if (
            expected_sha256 is not None
            and _sha256_of_file(dest, self.chunk_size) != expected_sha256.lower()
        ):
            return None  # corrupt/mismatched — replace with fresh download
        return dest

    def _download_attempt(
        self, url: str, dest: Path, expected_size: int | None, expected_sha256: str | None
    ) -> DownloadResult:
        part_path = dest.with_name(dest.name + PART_SUFFIX)

        # Resume decision: a .part file may be resumed ONLY with a
        # confirmed server Range response; otherwise restart cleanly.
        resume_from = 0
        if part_path.is_file():
            resume_from = part_path.stat().st_size

        headers: dict[str, str] = {}
        if resume_from > 0:
            headers["Range"] = f"bytes={resume_from}-"

        with requests.get(url, headers=headers, stream=True, timeout=self.timeout) as resp:
            # Range rejected -> server does not support resume: clean
            # restart (truncate the partial) rather than corrupting.
            if resume_from > 0 and resp.status_code != 206:
                resume_from = 0
                part_path.unlink(missing_ok=True)
                resp.raise_for_status()
            else:
                resp.raise_for_status()

            content_length = int(resp.headers.get("Content-Length", 0) or 0)
            if resume_from > 0 and content_length > 0:
                # Content-Range total = resume_from + remaining
                total = resume_from + content_length
            else:
                total = content_length
            if expected_size is not None and total > 0 and total != expected_size:
                return self._fail(
                    dest,
                    f"Server reports {total} bytes but expected {expected_size}",
                    DownloadStatus.FAILED,
                )

            self._progress = DownloadProgress(
                bytes_downloaded=resume_from,
                total_bytes=total or None,
                status=DownloadStatus.DOWNLOADING,
            )
            self._emit(self._progress)

            # Open for append when truly resuming; else fresh truncate.
            mode = "ab" if resume_from > 0 else "wb"
            sha = hashlib.sha256()
            if resume_from > 0:
                # Seed the hash with the resumed prefix (streamed).
                with open(part_path, "rb") as seed:
                    for chunk in iter(lambda: seed.read(self.chunk_size), b""):
                        sha.update(chunk)

            self.dest_dir.mkdir(parents=True, exist_ok=True)
            with open(part_path, mode) as fh:
                for chunk in resp.iter_content(chunk_size=self.chunk_size):
                    if self._cancelled:
                        # Leave the .part file (resumable); NEVER the
                        # final model name.  File closes via context.
                        self._emit(DownloadProgress(
                            bytes_downloaded=self._progress.bytes_downloaded,
                            total_bytes=self._progress.total_bytes,
                            status=DownloadStatus.CANCELLED,
                        ))
                        raise _Cancelled()
                    if not chunk:
                        continue
                    fh.write(chunk)
                    sha.update(chunk)
                    self._progress.bytes_downloaded += len(chunk)
                    self._progress.chunks_downloaded += 1
                    self._emit(self._progress)

        # ---- validation of the completed .part file ----
        final_size = part_path.stat().st_size
        if expected_size is not None and final_size != expected_size:
            part_path.unlink(missing_ok=True)
            return self._fail(
                dest,
                f"Size mismatch: downloaded {final_size} bytes, "
                f"expected {expected_size}",
                DownloadStatus.FAILED,
            )
        digest = sha.hexdigest()
        if expected_sha256 is not None and digest != expected_sha256.lower():
            # Checksum mismatch: remove the corrupt partial; NEVER
            # leave a falsely-complete model behind.
            part_path.unlink(missing_ok=True)
            return self._fail(
                dest,
                f"SHA-256 mismatch: expected {expected_sha256}, got {digest}",
                DownloadStatus.FAILED,
            )

        # ---- atomic completion ----
        os.replace(part_path, dest)
        logger.info(
            "Model downloaded: %s (%d bytes, sha256=%s)",
            dest.name, final_size, digest[:12] + "...",
        )
        return DownloadResult(
            success=True,
            dest=dest,
            size_bytes=final_size,
            checksum_sha256=digest,
            status=DownloadStatus.COMPLETED,
        )

    _progress = DownloadProgress()


class _Cancelled(Exception):
    """Internal control-flow sentinel for clean cancellation."""


class _LiveCancelFlag:
    """Truthy live view of a legacy wrapper's cancel state.

    ``ModelDownloader.download`` delegates to the secure machinery,
    which checks ``self._cancelled`` at every chunk boundary.  Passing
    the wrapper's *flag value* would snapshot it at delegation time —
    mid-flight ``wrapper.cancel()`` could never propagate.  This tiny
    forwarder evaluates the wrapper's CURRENT state on each check, so
    cooperative cancellation stays effective throughout the operation.
    """

    __slots__ = ("_wrapper",)

    def __init__(self, wrapper: ModelDownloader) -> None:
        self._wrapper = wrapper

    def __bool__(self) -> bool:
        return bool(self._wrapper._cancelled)


# --------------------------------------------------------------------------- #
# Legacy v1 surface (backward compatibility)
# --------------------------------------------------------------------------- #


class ModelDownloader:
    """Legacy v1 downloader (kept for backward compatibility).

    Prefer :class:`SecureModelDownloader`.  This class now delegates
    to the secure implementation with a fixed category dir so legacy
    call paths inherit the Phase 7 safety rules (part files, disk
    checks, checksum cleanup) while keeping their constructor shape.
    """

    def __init__(
        self,
        dest_dir: Path | str = "models",
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: int = DEFAULT_TIMEOUT,
        progress_callback: Callable[[DownloadProgress], None] | None = None,
    ) -> None:
        self.dest_dir = Path(dest_dir)
        self.chunk_size = chunk_size
        self.max_retries = max_retries
        self.timeout = timeout
        self._progress = DownloadProgress()
        self._progress_callback = progress_callback
        self._cancelled = False

    def download(
        self,
        url: str,
        filename: str,
        expected_checksum: str | None = None,
    ) -> DownloadResult:
        """Legacy download via the secure pipeline (category-dir scoped).

        The legacy call cannot express an expected size, so size
        validation is skipped but checksum, part-file and disk safety
        still apply.  ``dest_dir`` must be an existing category-style
        directory (created when missing).
        """
        self.dest_dir.mkdir(parents=True, exist_ok=True)
        secure = SecureModelDownloader.__new__(SecureModelDownloader)
        # Minimal rebind onto the secure attempt machinery.
        secure.category = "llm"
        secure.dest_dir = self.dest_dir
        secure._models_root = self.dest_dir.parent  # type: ignore[attr-defined]
        secure.chunk_size = max(64 * 1024, self.chunk_size)
        secure.timeout = self.timeout
        secure.max_retries = self.max_retries
        secure._progress_callback = self._progress_callback  # type: ignore[attr-defined]
        secure._validator = None  # type: ignore[attr-defined]
        # Live cancellation link: cancel() on this legacy wrapper must
        # reach the ACTIVE secure operation, not a start-time snapshot
        # of the flag.  The secure downloader consults its own flag at
        # every chunk boundary, so a simple forwarder object keeps the
        # wrapper's cancel() effective mid-download.
        secure._cancelled = _LiveCancelFlag(self)
        result = secure.download(
            url, filename, expected_size=None, expected_sha256=expected_checksum
        )
        self._cancelled = secure._cancelled
        return result

    def cancel(self) -> None:
        """Signal the download to cancel at the next chunk boundary."""
        self._cancelled = True

    @staticmethod
    def compute_checksum(path: Path) -> str:
        """Compute SHA-256 checksum of a file (streamed)."""
        return _sha256_of_file(Path(path), DEFAULT_CHUNK_SIZE)


__all__ = [
    "DISK_SAFETY_MARGIN_BYTES",
    "PART_SUFFIX",
    "DownloadProgress",
    "DownloadResult",
    "DownloadStatus",
    "ModelDownloader",
    "SecureModelDownloader",
    "check_disk_space",
]
