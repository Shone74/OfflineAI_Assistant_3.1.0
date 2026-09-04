"""Model download manager for the Installer System.

Downloads AI model files (GGUF, ONNX, etc.) with resume support,
checksum verification, retry logic, and progress reporting.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import requests

DEFAULT_CHUNK_SIZE = 1024 * 1024  # 1 MB chunks
DEFAULT_MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30  # seconds per chunk


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


class ModelDownloader:
    """Downloads model files with resume, checksum, and retry support."""

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
        """Download a model file to ``dest_dir / filename``.

        Resumes partial downloads (HTTP Range requests). Verifies
        SHA-256 checksum if ``expected_checksum`` is provided.
        Retries up to ``max_retries`` on transient failures.
        """
        self.dest_dir.mkdir(parents=True, exist_ok=True)
        dest = self.dest_dir / filename

        for attempt in range(1, self.max_retries + 1):
            if self._cancelled:
                self._cancelled = False
                return DownloadResult(
                    success=False,
                    dest=dest,
                    size_bytes=0,
                    checksum_sha256="",
                    status=DownloadStatus.CANCELLED,
                    error="Download cancelled by user",
                )
            try:
                result = self._download_attempt(url, dest, expected_checksum)
                if result.success:
                    return result
                if result.status == DownloadStatus.CANCELLED:
                    self._cancelled = False
                    return result
                # Retry on failure (transient network errors, checksum mismatch)
                if attempt < self.max_retries:
                    continue
                return result
            except requests.RequestException as exc:
                if attempt == self.max_retries:
                    return DownloadResult(
                        success=False,
                        dest=dest,
                        size_bytes=self._progress.bytes_downloaded,
                        checksum_sha256="",
                        status=DownloadStatus.FAILED,
                        error=f"Network error after {attempt} attempt(s): {exc}",
                    )
        # Should not reach here, but be explicit
        return DownloadResult(
            success=False,
            dest=dest,
            size_bytes=self._progress.bytes_downloaded,
            checksum_sha256="",
            status=DownloadStatus.FAILED,
            error="Max retries exhausted",
        )

    def cancel(self) -> None:
        """Signal the download to cancel at the next chunk boundary."""
        self._cancelled = True

    def _download_attempt(
        self, url: str, dest: Path, expected_checksum: str | None
    ) -> DownloadResult:
        # Determine resume offset from existing partial file
        resume_byte_pos = 0
        if dest.exists():
            resume_byte_pos = dest.stat().st_size

        headers: dict[str, str] = {}
        if resume_byte_pos > 0:
            headers["Range"] = f"bytes={resume_byte_pos}-"

        resp = requests.get(url, headers=headers, stream=True, timeout=self.timeout)
        if resp.status_code == 416:
            # Range not satisfiable — file is already complete
            return self._verify_or_complete(dest, expected_checksum, resume_byte_pos)

        resp.raise_for_status()

        total_size = int(resp.headers.get("Content-Length", 0))
        if resume_byte_pos > 0 and total_size > 0:
            total_size += resume_byte_pos

        self._progress = DownloadProgress(
            bytes_downloaded=resume_byte_pos,
            total_bytes=total_size or None,
            chunks_downloaded=0,
            status=DownloadStatus.DOWNLOADING,
        )

        mode = "ab" if resume_byte_pos > 0 else "wb"
        sha256 = hashlib.sha256()

        # If resuming, hash the existing content first
        if resume_byte_pos > 0:
            with open(dest, "rb") as f:
                for chunk in iter(lambda: f.read(self.chunk_size), b""):
                    sha256.update(chunk)

        with open(dest, mode) as f:
            for chunk in resp.iter_content(chunk_size=self.chunk_size):
                if self._cancelled:
                    return DownloadResult(
                        success=False,
                        dest=dest,
                        size_bytes=self._progress.bytes_downloaded,
                        checksum_sha256=sha256.hexdigest(),
                        status=DownloadStatus.CANCELLED,
                        error="Download cancelled",
                    )
                if chunk:
                    f.write(chunk)
                    sha256.update(chunk)
                    self._progress.bytes_downloaded += len(chunk)
                    self._progress.chunks_downloaded += 1
                    if self._progress_callback:
                        self._progress_callback(self._progress)

        checksum = sha256.hexdigest()

        # Verify checksum if provided
        if expected_checksum is not None and checksum != expected_checksum.lower():
            return DownloadResult(
                success=False,
                dest=dest,
                size_bytes=self._progress.bytes_downloaded,
                checksum_sha256=checksum,
                status=DownloadStatus.FAILED,
                error=(
                    f"Checksum mismatch: expected {expected_checksum}, "
                    f"got {checksum}"
                ),
            )

        return DownloadResult(
            success=True,
            dest=dest,
            size_bytes=self._progress.bytes_downloaded,
            checksum_sha256=checksum,
            status=DownloadStatus.COMPLETED,
        )

    def _verify_or_complete(
        self, dest: Path, expected_checksum: str | None, existing_size: int
    ) -> DownloadResult:
        """Handle 416 (range not satisfiable) — file already complete."""
        checksum = ""
        if expected_checksum is not None:
            sha256 = hashlib.sha256()
            with open(dest, "rb") as f:
                for chunk in iter(lambda: f.read(self.chunk_size), b""):
                    sha256.update(chunk)
            checksum = sha256.hexdigest()
            if checksum != expected_checksum.lower():
                return DownloadResult(
                    success=False,
                    dest=dest,
                    size_bytes=existing_size,
                    checksum_sha256=checksum,
                    status=DownloadStatus.FAILED,
                    error=f"Checksum mismatch on existing file: expected {expected_checksum}",
                )
        return DownloadResult(
            success=True,
            dest=dest,
            size_bytes=existing_size,
            checksum_sha256=checksum or "",
            status=DownloadStatus.COMPLETED,
        )

    @staticmethod
    def compute_checksum(path: Path) -> str:
        """Compute SHA-256 checksum of a file."""
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(DEFAULT_CHUNK_SIZE), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
