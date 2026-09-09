"""Hardware capability abstraction (PHASE 7).

A small, deterministic, testable information model over the machine's
relevant hardware: CPU cores/threads, RAM bytes, GPU name/vendor,
VRAM bytes, GPU/offload support, CUDA availability, and free disk
space on the user-selected models root.

Design contract:

* **No low-level WMI/pynvml/psutil details leak into the UI** — callers
  consume :class:`HardwareSnapshot` (bytes, counts, names, warnings).
* **Optional dependencies fail gracefully.**  Startup never depends on
  pynvml, pywin32/WMI, or llama-cpp-python: each probe is individually
  guarded and degrades to a deterministic "unknown" with a warning
  instead of raising.
* **No duplicate GPU APIs.**  GPU offload capability and VRAM come from
  the Phase 4 runtime (:mod:`ai.models.gpu_runtime`) — NVML-based and
  already hardened against missing drivers/CUDA/libraries.  The legacy
  installer WMI probe is retained only as a *name/vendor* hint and its
  unreliable ``AdapterRAM`` figure is never trusted for VRAM.
* **Disk space is measured on the user-selected models root** (Phase 3
  ``models.storage_root``), never on ``/`` — the models root may live
  on any drive, including external ones.

Documented limitations (do not claim more in UI/docs than this):

* Single-GPU: VRAM and offload figures describe GPU 0 only (Phase 4
  documented limitation — no multi-GPU splitting is configured).
* VRAM may be *unknown* (``vram_bytes == 0``) when pynvml/NVML is
  unavailable or initialization fails — consumers must treat this as
  "conservative CPU strategy", never as "no GPU".
* WMI ``AdapterRAM`` is 32-bit wrapped for VRAM > 4 GB on some systems
  and reports shared memory on others — it is used only to display a
  GPU name/vendor, never for sizing decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.logger import get_logger

logger = get_logger("ai.hardware")

#: Bytes per GiB for readable conversions.
GIB = 1024**3


@dataclass(frozen=True, slots=True)
class HardwareSnapshot:
    """Deterministic snapshot of the hardware relevant to local AI models.

    All byte quantities are ints (never floats) so comparisons and
    progress math stay exact.  ``None``/0 values mean "unknown", never
    "absent" — check the *supported flags before drawing conclusions.
    """

    cpu_name: str = "Unknown CPU"
    cpu_cores: int = 0
    cpu_threads: int = 0
    ram_total_bytes: int = 0
    gpu_name: str = ""
    gpu_vendor: str = ""
    vram_bytes: int = 0  # 0 == unknown
    gpu_offload_supported: bool = False
    cuda_available: bool = False
    disk_free_bytes: int | None = None  # models-root drive; None = unknown
    warnings: tuple[str, ...] = field(default_factory=tuple)

    # -- derived, human-readable facts (no implementation details) ------
    @property
    def ram_total_gb(self) -> float:
        return self.ram_total_bytes / GIB

    @property
    def vram_gb(self) -> float | None:
        return self.vram_bytes / GIB if self.vram_bytes else None

    @property
    def vram_known(self) -> bool:
        return self.vram_bytes > 0

    @property
    def disk_free_known(self) -> bool:
        return self.disk_free_bytes is not None

    def to_summary_lines(self) -> list[str]:
        """Plain-language hardware summary for UI display."""
        lines = [
            f"CPU: {self.cpu_name} ({self.cpu_cores} cores / {self.cpu_threads} threads)",
            f"RAM: {self.ram_total_gb:.0f} GB",
        ]
        if self.gpu_name:
            gpu_line = f"GPU: {self.gpu_name}"
            if self.gpu_vendor:
                gpu_line += f" ({self.gpu_vendor})"
            if self.vram_known:
                gpu_line += f" — {self.vram_gb:.1f} GB VRAM"
            else:
                gpu_line += " — VRAM unknown"
            lines.append(gpu_line)
        else:
            lines.append("GPU: none detected")
        lines.append("GPU acceleration: available" if self.gpu_offload_supported
                     else "GPU acceleration: unavailable (CPU mode)")
        if self.disk_free_known:
            lines.append(f"Free space on models drive: {self.disk_free_bytes / GIB:.0f} GB")
        else:
            lines.append("Free space on models drive: unknown")
        for warning in self.warnings:
            lines.append(f"Note: {warning}")
        return lines


def _detect_cpu_name() -> str:
    try:
        import platform

        return platform.processor() or "Unknown CPU"
    except Exception:
        return "Unknown CPU"


def _detect_cpu_counts() -> tuple[int, int]:
    try:
        import psutil

        cores = psutil.cpu_count(logical=False) or 1
        threads = psutil.cpu_count(logical=True) or cores
        return int(cores), int(threads)
    except Exception:
        return 1, 1


def _detect_ram_bytes() -> int:
    try:
        import psutil

        return int(psutil.virtual_memory().total)
    except Exception:
        return 0


def _detect_gpu_name_vendor() -> tuple[str, str]:
    """Best-effort GPU name/vendor hint via the legacy installer probe.

    Deliberately does NOT return VRAM: WMI ``AdapterRAM`` is unreliable
    (32-bit wrapped above 4 GB; reports shared memory on integrated
    GPUs).  VRAM comes from the Phase 4 NVML probe instead.
    """
    try:
        from installer.hardware import _detect_gpu

        brand, name, _vram_untrusted, _cuda = _detect_gpu()
        return name or "", brand.value if brand else ""
    except Exception:
        return "", ""


def free_disk_bytes_for_root(models_root: Path) -> int | None:
    """Free bytes on the drive containing *models_root*.

    PHASE 3/7: the models root is user-selected and may sit on ANY
    drive — this measures THAT drive, never ``/`` or the app drive.
    Returns ``None`` when the value cannot be determined (probe must
    never raise); callers treat it as "unknown, allow download with
    runtime-error fallback" rather than inventing a number.
    """
    try:
        import psutil

        probe_dir = models_root if models_root.exists() else models_root.anchor
        if not str(probe_dir):
            return None
        return int(psutil.disk_usage(str(probe_dir)).free)
    except Exception:
        return None


def _validate_models_root(models_root: str | Path | None) -> Path | None:
    """Normalize the models-root argument; absolute only (never CWD)."""
    if models_root is None:
        from core.paths import get_models_root

        models_root = get_models_root()
    root = Path(models_root)
    if not root.is_absolute():
        logger.warning(
            "HardwareSnapshot: models root must be absolute; got %r — "
            "using canonical resolution instead", models_root,
        )
        from core.paths import get_models_root

        root = get_models_root()
    return root


def detect_hardware_snapshot(
    models_root: str | Path | None = None,
    *,
    refresh_gpu: bool = False,
) -> HardwareSnapshot:
    """Build a :class:`HardwareSnapshot` from the machine's hardware.

    * *models_root* defaults to the canonical ``models.storage_root``
      resolution (Phase 3) — never a fixed path, never the CWD.
    * *refresh_gpu* forces a fresh Phase 4 GPU capability detection
      (cached per process by default).

    Every probe degrades to a safe unknown value instead of raising:
    application startup never depends on optional hardware libraries.
    """
    warnings: list[str] = []

    cpu_name = _detect_cpu_name()
    cpu_cores, cpu_threads = _detect_cpu_counts()
    ram_total = _detect_ram_bytes()

    # Phase 4 GPU runtime is the authoritative offload/VRAM source.
    gpu_name, gpu_vendor = _detect_gpu_name_vendor()
    try:
        from ai.models.gpu_runtime import detect_gpu_capabilities

        caps = detect_gpu_capabilities(refresh=refresh_gpu)
        offload = caps.offload_supported
        vram = caps.vram_bytes if caps.vram_known else 0
        if offload and not caps.vram_known:
            warnings.append("GPU offload supported but VRAM could not be "
                            "determined — conservative sizing applies")
        warnings.extend(caps.warnings)
    except Exception as exc:
        offload, vram = False, 0
        warnings.append(f"GPU capability detection failed: {exc}")

    cuda = bool(gpu_vendor.lower() == "nvidia" and offload)

    root = _validate_models_root(models_root)
    disk_free = free_disk_bytes_for_root(root) if root is not None else None

    snapshot = HardwareSnapshot(
        cpu_name=cpu_name,
        cpu_cores=cpu_cores,
        cpu_threads=cpu_threads,
        ram_total_bytes=ram_total,
        gpu_name=gpu_name,
        gpu_vendor=gpu_vendor,
        vram_bytes=vram,
        gpu_offload_supported=offload,
        cuda_available=cuda,
        disk_free_bytes=disk_free,
        warnings=tuple(warnings),
    )
    logger.debug("HardwareSnapshot: cpu=%s ram=%.0fGB gpu=%s vram=%d disk_free=%s",
                 cpu_name, ram_total / GIB if ram_total else 0, gpu_name,
                 vram, disk_free)
    return snapshot
