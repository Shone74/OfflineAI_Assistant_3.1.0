"""Deterministic model-fit recommendation layer (PHASE 7).

Classifies a *candidate model* against the *detected hardware* into
one of a fixed set of verdicts.  It answers "can this machine run this
model, and how?" — the curated *size* recommendation (which model class
to prefer) stays with :func:`installer.hardware.recommend_model`.

Contract:

* Deterministic and pure: same inputs -> same verdict, no wall-clock,
  no benchmark numbers, no invented performance claims.
* **Never** claims a model is "guaranteed to fit" merely because the
  raw file size is below VRAM: the Phase 4 conservative estimator
  (file size x overhead factor + KV-cache allowance) is reused
  verbatim — a fit verdict means "fits within the safe budget".
* Reuses the Phase 4 strategy decision (:func:`decide_gpu_layers`)
  for the GPU plan so recommendation and runtime can never disagree.
* Considers: VRAM, system RAM, model file size, category, context
  size, free disk space on the models-root drive, GPU mode, and CPU
  offload support.

RAM rules (CPU planning only — VRAM rules govern GPU offload):

* A model estimated larger than total RAM is rejected regardless of
  GPU plans (partial offload still needs RAM for the CPU share, and
  paging a model kills usability deterministically).
* Embedding/STT categories are RAM-planned (they run outside the
  llama.cpp GPU offload path).

Disk rules:

* When the expected download size plus a safety margin exceeds free
  space on the models-root drive, the verdict is
  ``INSUFFICIENT_DISK`` — before any bytes are fetched.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ai.hardware import HardwareSnapshot
from ai.models.gpu_runtime import (
    ExecutionMode,
    GPUStrategy,
    estimate_model_vram_bytes,
)
from core.logger import get_logger

logger = get_logger("ai.recommendation")

#: Extra head-room required on the models drive beyond the download
#: size (decompress scratch, companion files, filesystem overhead).
DISK_SAFETY_MARGIN_BYTES = 512 * 1024 * 1024  # 512 MiB

#: Conservative share of system RAM a model may occupy for CPU-only
#: planning (OS + app + browser must survive alongside).
_RAM_USABLE_FRACTION = 0.9


class ModelVerdict(str, Enum):
    """Fixed classification verdicts for a candidate model."""

    RECOMMENDED = "recommended"          # full GPU offload, fits safely
    POSSIBLE = "possible"                # partial GPU offload works
    CPU_RECOMMENDED = "cpu_recommended"  # runs, but on CPU only
    INSUFFICIENT_RESOURCES = "insufficient_resources"  # RAM/VRAM too small
    INSUFFICIENT_DISK = "insufficient_disk"  # models drive too full
    UNKNOWN = "unknown"                  # cannot determine


@dataclass(frozen=True, slots=True)
class ModelRequirements:
    """Hardware requirements of a candidate downloadable model.

    *file_size_bytes* is the dominant signal (GGUF weights).  For LLM
    category entries, *n_ctx* drives the KV-cache estimate through the
    Phase 4 estimator.  Embedding/STT entries pass ``n_ctx=0`` (their
    memory profile is dominated by the file itself).
    """

    file_size_bytes: int
    category: str  # llm | embedding | stt (MODEL_CATEGORIES)
    n_ctx: int = 0

    def __post_init__(self) -> None:
        if self.file_size_bytes < 0:
            raise ValueError("file_size_bytes must be >= 0")
        if self.n_ctx < 0:
            raise ValueError("n_ctx must be >= 0")


@dataclass(frozen=True, slots=True)
class RecommendationResult:
    """Verdict + machine-readable reason for a candidate model."""

    verdict: ModelVerdict
    reason: str
    estimated_memory_bytes: int = 0
    gpu_strategy: GPUStrategy | None = None

    @property
    def is_runnable(self) -> bool:
        return self.verdict in (
            ModelVerdict.RECOMMENDED,
            ModelVerdict.POSSIBLE,
            ModelVerdict.CPU_RECOMMENDED,
        )


def evaluate_model_fit(
    requirements: ModelRequirements,
    hardware: HardwareSnapshot,
    *,
    gpu_mode: str = "auto",
    download_size_bytes: int | None = None,
) -> RecommendationResult:
    """Classify *requirements* against *hardware* (deterministic).

    *gpu_mode* is the Phase 4 ``ai.gpu_mode`` setting (auto/cpu/gpu).
    *download_size_bytes* defaults to ``file_size_bytes`` when None;
    pass the actual download payload size (e.g. excluding companions
    already on disk) for the disk check.

    Decision order (each step can return early — deterministic):

    1. Unknown hardware facts that block ANY verdict -> UNKNOWN.
    2. Disk check: download + margin > free space -> INSUFFICIENT_DISK.
    3. Memory estimate (Phase 4 estimator for llm; file size for
       embedding/stt).  Estimate above usable RAM -> INSUFFICIENT_RESOURCES.
    4. CPU-forced mode or no offload support -> CPU_RECOMMENDED (when
       the RAM check passed) — the model runs, just on CPU.
    5. Phase 4 strategy decision for the llm category:
       FULL_GPU -> RECOMMENDED, PARTIAL_GPU -> POSSIBLE,
       CPU_ONLY -> CPU_RECOMMENDED (with the reason string).
    """

    # 1. Blocking unknowns: without RAM we cannot plan anything.
    if hardware.ram_total_bytes <= 0:
        return RecommendationResult(
            ModelVerdict.UNKNOWN, "System RAM could not be determined"
        )

    # 2. Disk-space check on the actual models-root drive.
    download_bytes = (
        download_size_bytes
        if download_size_bytes is not None
        else requirements.file_size_bytes
    )
    if (
        download_bytes > 0
        and hardware.disk_free_bytes is not None
        and download_bytes + DISK_SAFETY_MARGIN_BYTES > hardware.disk_free_bytes
    ):
        return RecommendationResult(
            ModelVerdict.INSUFFICIENT_DISK,
            f"Download needs ~{download_bytes / (1024**3):.1f} GB + safety "
            f"margin but only {hardware.disk_free_bytes / (1024**3):.1f} GB "
            f"free on the models drive",
        )

    # 3. Memory estimate.
    if requirements.category == "llm":
        estimated = estimate_model_vram_bytes(
            requirements.file_size_bytes, requirements.n_ctx
        )
    else:
        # Embedding/STT run outside the llama.cpp offload path; their
        # memory profile is the (decompressed) file itself plus modest
        # activation memory — file size is the deterministic signal.
        estimated = requirements.file_size_bytes

    usable_ram = int(hardware.ram_total_bytes * _RAM_USABLE_FRACTION)
    if estimated > usable_ram:
        return RecommendationResult(
            ModelVerdict.INSUFFICIENT_RESOURCES,
            f"Model needs ~{estimated / (1024**3):.1f} GB but only "
            f"{usable_ram / (1024**3):.1f} GB of system RAM is usable",
            estimated_memory_bytes=estimated,
        )

    # 4. Categories without a GPU path, forced-CPU mode, or no offload
    #    support: CPU verdict (RAM check already passed).
    cpu_only = (
        requirements.category in ("embedding", "stt")
        or gpu_mode == "cpu"
        or not hardware.gpu_offload_supported
    )
    if cpu_only:
        reason = (
            "Runs on CPU (no GPU offload path for this category)"
            if requirements.category in ("embedding", "stt")
            else "GPU mode forced to CPU"
            if gpu_mode == "cpu"
            else "GPU acceleration unavailable — CPU mode"
        )
        return RecommendationResult(
            ModelVerdict.CPU_RECOMMENDED,
            reason,
            estimated_memory_bytes=estimated,
            gpu_strategy=GPUStrategy.CPU_ONLY,
        )

    # 5. Phase 4 centralized strategy decision for GPU offload.
    from ai.models.gpu_runtime import decide_gpu_layers

    decision = decide_gpu_layers(
        model_size_bytes=requirements.file_size_bytes,
        n_ctx=requirements.n_ctx,
        # Build a snapshot the Phase 4 decision understands; VRAM
        # unknown keeps its conservative CPU behavior.
        capabilities=_as_capabilities(hardware),
        mode=gpu_mode if gpu_mode in ("auto", "cpu", "gpu") else ExecutionMode.AUTO,
    )
    verdict = {
        GPUStrategy.FULL_GPU: ModelVerdict.RECOMMENDED,
        GPUStrategy.PARTIAL_GPU: ModelVerdict.POSSIBLE,
        GPUStrategy.CPU_ONLY: ModelVerdict.CPU_RECOMMENDED,
    }[decision.strategy]
    return RecommendationResult(
        verdict,
        decision.reason,
        estimated_memory_bytes=estimated,
        gpu_strategy=decision.strategy,
    )


def _as_capabilities(hardware: HardwareSnapshot):
    """Adapt HardwareSnapshot to the Phase 4 GPUCapabilities shape."""
    from ai.models.gpu_runtime import GPUCapabilities

    return GPUCapabilities(
        offload_supported=hardware.gpu_offload_supported,
        vram_bytes=hardware.vram_bytes,
        vram_source="hardware-snapshot",
    )
