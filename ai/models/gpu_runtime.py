"""GPU / CUDA runtime architecture (PHASE 4).

Single centralized decision point for GPU capability detection, CUDA DLL
discovery, and safe GPU-layer selection for the llama.cpp backend.

Design contract:

* ``CPU_ONLY``   — no GPU offload (no capable GPU, CPU-only llama.cpp build,
                   user-forced CPU, or a model that cannot be offloaded
                   safely).
* ``FULL_GPU``   — offload every layer (llama.cpp caps the magic value at
                   the model's real layer count).
* ``PARTIAL_GPU``— offload a bounded share of layers when the model clearly
                   exceeds available VRAM but partial offload is still
                   beneficial.

Safety rules:

* The magic full-offload value is NEVER used as a universal strategy: a
  model significantly larger than available VRAM must not receive it.
* File size is a *lower bound* estimate, not the exact VRAM requirement —
  a conservative overhead factor plus a KV-cache/context estimate is
  applied on top (see :func:`estimate_model_vram_bytes`).
* All optional dependencies (llama-cpp-python, pynvml) are handled
  gracefully: missing, failing, or permission-denied NVML never crashes
  model loading — detection simply reports VRAM as unknown and the
  strategy degrades conservatively.
* Detection failures degrade to CPU mode; CPU-only machines remain fully
  functional.

Single-GPU limitation: llama-cpp-python's ``n_gpu_layers`` offload path
targets GPU 0 (the active CUDA device). Multi-GPU splitting (e.g.
ggml split across devices) is not configured by this module; VRAM is
read from device 0 only. This matches the existing project architecture
and is a documented limitation, not an abstraction for every GPU found.

CUDA DLL discovery (Windows): the loader does NOT rely exclusively on
``sys.path``. Candidate roots, in order:

1. Explicitly registered directories (``register_cuda_dll_dir``) — the
   extension point PHASE 5 (frozen packaging) will use to add bundled
   native/CUDA locations without touching this architecture.
2. The ``nvidia`` namespace package layout (``importlib.util.find_spec``)
   including its real on-disk subpackage roots (works even when
   ``sys.path`` entries differ from the package location).
3. Python purelib/platlib site directories from ``sysconfig`` (covers
   pip-installed ``nvidia-*`` wheels in virtual environments where
   ``sys.path`` may be incomplete).
4. ``sys.path`` entries themselves (legacy behaviour, kept as one
   additional source, never the only one).

Each discovered directory containing native NVIDIA runtime libraries is
registered with :func:`os.add_dll_directory` (the robust, per-process
mechanism on Windows) and also prepended to ``PATH`` (belt-and-braces for
native code that only consults the environment). Non-Windows platforms
are a no-op.

No developer-specific CUDA installation path (e.g. a CUDA Toolkit
location) is ever hardcoded.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from core.logger import get_logger

logger = get_logger("gpu_runtime")

# llama.cpp interprets any value >= the model's layer count as "offload all".
# Exported for tests and callers; never used blindly — see decide_gpu_layers.
GPU_LAYER_MAGIC_FULL = 999

# Conservative runtime overhead factor applied on top of the GGUF file size
# (weights are the bulk, but compute buffers/graphs add real overhead).
_MODEL_OVERHEAD_FACTOR = 1.15

# Fraction of VRAM reserved (never planned for weights) for KV cache,
# fragmentation, display/other processes, and llama.cpp workspace buffers.
_VRAM_RESERVE_FRACTION = 0.15

# Bytes per KV-cache element group: empirical conservative estimate for
# fp16 K+V per token across common architectures (2 * d_head * n_layer * 2B
# rounds to roughly this for 4k-8k head models). Deliberately conservative.
_KV_BYTES_PER_TOKEN = 64 * 1024  # 64 KB/token

# Minimum layer count worth offloading when falling back to partial mode
# (offloading fewer than this yields no measurable benefit).
_MIN_PARTIAL_LAYERS = 8


class ExecutionMode(str, Enum):
    """User-facing GPU execution mode configuration."""

    AUTO = "auto"   # detect capabilities, choose safe strategy
    CPU = "cpu"     # force CPU-only
    GPU = "gpu"     # prefer GPU, degrade safely when unsupported


class GPUStrategy(str, Enum):
    """Internal strategy selected per model load."""

    CPU_ONLY = "cpu_only"
    PARTIAL_GPU = "partial_gpu"
    FULL_GPU = "full_gpu"


@dataclass(frozen=True)
class GPUCapabilities:
    """Snapshot of runtime GPU capabilities.

    Attributes:
        offload_supported: llama.cpp backend supports GPU offload (the
            authoritative check — a CUDA-capable machine with a CPU-only
            llama.cpp build reports ``False``).
        vram_bytes: total VRAM of GPU 0 in bytes; ``0`` when unknown
            (NVML missing, initialization failed, or no NVIDIA GPU).
        vram_source: human-readable origin of the VRAM figure (for logs).
        warnings: non-fatal detection warnings worth surfacing.
    """

    offload_supported: bool = False
    vram_bytes: int = 0
    vram_source: str = "unknown"
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def vram_known(self) -> bool:
        return self.vram_bytes > 0


# --------------------------------------------------------------------------- #
# CUDA DLL discovery
# --------------------------------------------------------------------------- #

# Explicit extension point for frozen/alternative layouts (PHASE 5 will
# register bundled DLL directories here at startup; nothing in PHASE 4
# populates it from packaging concerns).
_extra_dll_dirs: list[Path] = []


def register_cuda_dll_dir(path: str | Path) -> Path | None:
    """Register an explicit CUDA/native DLL directory.

    Returns the resolved directory, or ``None`` when the path is not
    absolute or does not exist (registration is ignored so callers can
    log/act accordingly).  This is the PHASE 5 integration point.
    """
    candidate = Path(path)
    if not candidate.is_absolute():
        logger.warning(
            "register_cuda_dll_dir ignored relative path: %s", candidate
        )
        return None
    if not candidate.is_dir():
        logger.debug("register_cuda_dll_dir: directory does not exist: %s", candidate)
        return None
    resolved = candidate.resolve()
    if resolved not in _extra_dll_dirs:
        _extra_dll_dirs.append(resolved)
    return resolved


def _candidate_nvidia_roots() -> list[Path]:
    """Gather candidate ``nvidia`` package roots from multiple sources."""
    roots: list[Path] = []
    seen: set[Path] = set()

    def _add(candidate: Path) -> None:
        try:
            resolved = candidate.resolve(strict=False)
        except OSError:
            return
        if resolved in seen:
            return
        seen.add(resolved)
        roots.append(resolved)

    # 1. The nvidia namespace package itself (most robust — resolves via
    #    the import system, not sys.path strings).
    try:
        import importlib.util

        spec = importlib.util.find_spec("nvidia")
        if spec is not None and spec.submodule_search_locations:
            for loc in spec.submodule_search_locations:
                _add(Path(loc))
    except (ImportError, ValueError, ModuleNotFoundError):
        pass

    # 2. sysconfig purelib/platlib (virtualenvs, alternate install schemes).
    try:
        import sysconfig

        for scheme_key in ("purelib", "platlib"):
            loc = sysconfig.get_paths().get(scheme_key)
            if loc:
                _add(Path(loc) / "nvidia")
    except Exception:
        pass

    # 3. sys.path entries (legacy source — kept, but never the only one).
    for entry in sys.path:
        if not entry:
            continue
        try:
            _add(Path(entry) / "nvidia")
        except OSError:
            continue

    return roots


def discover_cuda_dll_dirs() -> list[Path]:
    """Return directories that may contain NVIDIA CUDA runtime DLLs.

    Combines explicitly registered directories (extension point) with the
    ``nvidia`` pip-package layout discovered through the import system,
    ``sysconfig`` site directories, and ``sys.path`` entries.  The result is
    informational; :func:`apply_cuda_dll_discovery` registers the existing
    ones with the OS loader.
    """
    dirs: list[Path] = []
    seen: set[Path] = set()

    for explicit in _extra_dll_dirs:
        if explicit not in seen:
            seen.add(explicit)
            dirs.append(explicit)

    for root in _candidate_nvidia_roots():
        if not root.is_dir():
            continue
        try:
            cu_dirs = sorted(root.iterdir(), reverse=True)
        except OSError:
            continue
        for cu_dir in cu_dirs:
            if not cu_dir.is_dir() or not cu_dir.name.startswith("cu"):
                continue
            for bin_sub in ("bin", "bin/x86_64"):
                bin_path = cu_dir / bin_sub
                if bin_path.is_dir():
                    try:
                        resolved = bin_path.resolve()
                    except OSError:
                        continue
                    if resolved not in seen:
                        seen.add(resolved)
                        dirs.append(resolved)
    return dirs


_applied_dll_dirs: list[Path] = []


def apply_cuda_dll_discovery() -> list[Path]:
    """Discover and register CUDA DLL directories (Windows only).

    Uses both :func:`os.add_dll_directory` (robust per-process loader
    registration) and PATH augmentation.  Safe to call repeatedly and from
    any platform; failures are logged at debug level and never raised —
    a missing CUDA stack must not crash the application, it simply means
    GPU offload stays unavailable and the runtime stays on CPU.
    """
    if sys.platform != "win32":
        return []
    applied: list[Path] = []
    try:
        for dll_dir in discover_cuda_dll_dirs():
            if dll_dir in _applied_dll_dirs:
                continue
            os.add_dll_directory(str(dll_dir))
            current_path = os.environ.get("PATH", "")
            if str(dll_dir) not in current_path:
                os.environ["PATH"] = os.pathsep.join([str(dll_dir), current_path])
            _applied_dll_dirs.append(dll_dir)
            applied.append(dll_dir)
        if applied:
            logger.debug(
                "Registered %d CUDA DLL directory(ies): %s",
                len(applied),
                ", ".join(str(d) for d in applied),
            )
    except Exception as exc:
        logger.debug("CUDA DLL discovery failed (continuing on CPU): %s", exc)
    return applied


# --------------------------------------------------------------------------- #
# Capability detection
# ---------------------------------------------------------------------------


def _llama_supports_offload() -> bool:
    """Ask the llama.cpp backend whether GPU offload is compiled in.

    Returns ``False`` when llama-cpp-python is not installed at all (CPU
    machines and test environments stay fully functional).
    """
    try:
        from llama_cpp import llama_supports_gpu_offload

        return bool(llama_supports_gpu_offload())
    except Exception:
        return False


def _read_vram_via_nvml() -> tuple[int, str, list[str]]:
    """Read GPU-0 total VRAM through NVML (pynvml), safely.

    Returns ``(vram_bytes, source, warnings)``.  Every failure mode —
    package missing, ``nvmlInit`` failing (no driver / permissions), no
    device, transient errors — returns ``(0, source, [warning])`` instead
    of raising.  NVML is always shut down when it was initialized here.
    """
    warnings: list[str] = []
    try:
        import pynvml
    except ImportError:
        return 0, "nvml-missing", [
            "pynvml (nvidia-ml-py3) not installed — VRAM unknown"
        ]
    except Exception as exc:
        return 0, "nvml-error", [f"pynvml import failed: {exc}"]

    initialized = False
    try:
        pynvml.nvmlInit()
        initialized = True
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        return int(info.total), "nvml", warnings
    except Exception as exc:
        warnings.append(f"NVML initialization/read failed: {exc}")
        return 0, "nvml-error", warnings
    finally:
        if initialized:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass


def detect_gpu_capabilities(refresh: bool = False) -> GPUCapabilities:
    """Detect runtime GPU capabilities (single detection point).

    Order of operations:

    1. Register CUDA DLL directories (so a freshly discovered stack can be
       used by the import below).
    2. Ask llama.cpp whether GPU offload is supported at all.
    3. Read GPU-0 VRAM via NVML when available.

    The result is cached per process; call with ``refresh=True`` to re-detect
    (used by tests).  ``offload_supported=False`` short-circuits VRAM probing
    (a CPU-only llama.cpp build makes VRAM irrelevant for this process).
    """
    global _capabilities_cache
    if _capabilities_cache is not None and not refresh:
        return _capabilities_cache

    apply_cuda_dll_discovery()
    offload = _llama_supports_offload()
    if not offload:
        cap = GPUCapabilities(
            offload_supported=False,
            vram_bytes=0,
            vram_source="llama-cpu-build-or-missing",
            warnings=(
                (
                    "llama.cpp GPU offload unavailable (CPU-only build or "
                    "llama-cpp-python not installed)"
                ),
            ),
        )
        logger.info("GPU offload unavailable — CPU mode")
        _capabilities_cache = cap
        return cap

    vram, source, warnings = _read_vram_via_nvml()
    cap = GPUCapabilities(
        offload_supported=True,
        vram_bytes=vram,
        vram_source=source,
        warnings=tuple(warnings),
    )
    if vram > 0:
        logger.info(
            "GPU offload supported — VRAM (GPU 0): %.1f GB [source=%s]",
            vram / (1024**3),
            source,
        )
    else:
        logger.info(
            "GPU offload supported but VRAM unknown [source=%s] — using "
            "conservative strategy",
            source,
        )
    _capabilities_cache = cap
    return cap


_capabilities_cache: GPUCapabilities | None = None


# --------------------------------------------------------------------------- #
# Memory estimation
# --------------------------------------------------------------------------- #


def estimate_model_vram_bytes(model_size_bytes: int, n_ctx: int) -> int:
    """Conservative estimate of the memory needed to run the model.

    Not an exact tensor-memory calculation: GGUF file size is the dominant
    lower bound (quantized weights), plus:

    * a fixed overhead factor for compute buffers and graph memory;
    * a per-token KV-cache allowance scaled by the configured context
      length (upper-bound style — safe, predictable behavior over maximum
      utilization).

    Returns ``0`` for degenerate inputs.
    """
    if model_size_bytes <= 0:
        return 0
    ctx = max(0, int(n_ctx))
    kv_estimate = ctx * _KV_BYTES_PER_TOKEN
    return int(model_size_bytes * _MODEL_OVERHEAD_FACTOR + kv_estimate)


# --------------------------------------------------------------------------- #
# GPU layer decision
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class GPUDecision:
    """Result of the centralized GPU strategy decision."""

    n_gpu_layers: int
    strategy: GPUStrategy
    reason: str

    @property
    def is_cpu(self) -> bool:
        return self.strategy is GPUStrategy.CPU_ONLY


def decide_gpu_layers(
    *,
    model_size_bytes: int,
    n_ctx: int,
    capabilities: GPUCapabilities | None = None,
    mode: str | ExecutionMode = ExecutionMode.AUTO,
    manual_layers: int | None = None,
) -> GPUDecision:
    """Decide the safe GPU strategy for loading a specific model.

    This is the single centralized decision point (never duplicated in
    loaders).  Parameters:

    * ``model_size_bytes`` — GGUF file size on disk.
    * ``n_ctx`` — configured context length (drives the KV estimate).
    * ``capabilities`` — pass a pre-detected snapshot; ``None`` detects
      fresh (tests inject fakes here).
    * ``mode`` — the user configuration ``ai.gpu_mode`` (auto / cpu / gpu).
    * ``manual_layers`` — expert override (``ai.n_gpu_layers`` > 0).
      Manual values are honored *after* basic sanity validation but are
      documented expert behavior: they bypass the conservative sizing
      only insofar as the user explicitly asked for it, and are still
      rejected for impossible situations (no offload support, CPU mode).

    Strategy (all quantities in bytes unless stated):

    1. CPU mode forced / no offload support / no model info → CPU_ONLY.
    2. VRAM unknown (detection failed) → conservative CPU_ONLY with a
       warning-capable reason (never blind full offload).
    3. Estimated memory fits within the safe VRAM budget (total VRAM minus
       the reserve fraction) → FULL_GPU.
    4. Model clearly exceeds total VRAM → CPU_ONLY (offloading a tiny
       fraction of a >VRAM model starves it; llama.cpp would page
       constantly).
    5. Between those: partial offload — the share of the safe budget the
       model would occupy maps to a layer share, floored at
       ``_MIN_PARTIAL_LAYERS`` layers, else CPU_ONLY.
    """
    caps = capabilities if capabilities is not None else detect_gpu_capabilities()
    if isinstance(mode, str):
        try:
            mode = ExecutionMode(mode.lower())
        except ValueError:
            mode = ExecutionMode.AUTO

    # 1. Forced CPU / unsupported / missing model info.
    if mode is ExecutionMode.CPU:
        return GPUDecision(0, GPUStrategy.CPU_ONLY, "GPU mode forced to CPU")
    if not caps.offload_supported:
        return GPUDecision(
            0, GPUStrategy.CPU_ONLY, "llama.cpp GPU offload unavailable"
        )
    if model_size_bytes <= 0:
        return GPUDecision(0, GPUStrategy.CPU_ONLY, "model size unknown")

    # Expert override — validated, never silently bypassing hard limits.
    if manual_layers is not None and manual_layers > 0:
        return GPUDecision(
            manual_layers,
            GPUStrategy.PARTIAL_GPU if manual_layers < GPU_LAYER_MAGIC_FULL else GPUStrategy.FULL_GPU,
            f"manual override n_gpu_layers={manual_layers} (expert setting)",
        )

    # 2. VRAM unknown — do not gamble on full offload.
    if not caps.vram_known:
        return GPUDecision(
            0,
            GPUStrategy.CPU_ONLY,
            f"VRAM unknown [{caps.vram_source}] — conservative CPU mode",
        )

    estimated = estimate_model_vram_bytes(model_size_bytes, n_ctx)
    total_vram = caps.vram_bytes
    safe_budget = int(total_vram * (1.0 - _VRAM_RESERVE_FRACTION))

    # 3. Comfortable fit → full offload.
    if estimated <= safe_budget:
        return GPUDecision(
            GPU_LAYER_MAGIC_FULL,
            GPUStrategy.FULL_GPU,
            f"model est. {estimated / (1024**3):.1f} GB fits safe VRAM budget "
            f"{safe_budget / (1024**3):.1f} GB of {total_vram / (1024**3):.1f} GB",
        )

    # 4. Clearly exceeds total VRAM (not just the budget) → CPU.
    if estimated > total_vram:
        return GPUDecision(
            0,
            GPUStrategy.CPU_ONLY,
            f"model est. {estimated / (1024**3):.1f} GB exceeds total VRAM "
            f"{total_vram / (1024**3):.1f} GB — CPU mode",
        )

    # 5. Partial fit — scale layers by the fraction of the safe budget
    #    the model would occupy (more of the model on GPU when there is
    #    more room), floored at a minimum useful offload.
    share = safe_budget / estimated if estimated else 0.0
    # Typical models have 24–80 layers; 48 is a safe planning denominator.
    planned_layers = int(48 * share)
    if planned_layers < _MIN_PARTIAL_LAYERS:
        return GPUDecision(
            0,
            GPUStrategy.CPU_ONLY,
            "partial offload share below useful minimum — CPU mode",
        )
    return GPUDecision(
        planned_layers,
        GPUStrategy.PARTIAL_GPU,
        f"model est. {estimated / (1024**3):.1f} GB partially fits safe VRAM "
        f"budget {safe_budget / (1024**3):.1f} GB — offloading {planned_layers} layers",
    )
