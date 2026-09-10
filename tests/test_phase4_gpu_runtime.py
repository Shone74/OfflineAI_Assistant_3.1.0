"""PHASE 4 regression tests — GPU / CUDA runtime architecture.

All tests run without an NVIDIA GPU and without llama-cpp-python by
injecting deterministic fake capabilities.  Locks down:

* CPU_ONLY / FULL_GPU / PARTIAL_GPU strategy selection
* capability detection (offload flag, NVML safety, VRAM sources)
* CUDA DLL discovery that is NOT sys.path-only (import-system +
  sysconfig + explicit extension point)
* the universal ``999`` never returns as an automatic strategy
* RTX-3080-class 10 GB VRAM vs. a ~14 GB model → partial/CPU, never auto
  FULL_GPU
* manual expert override validation
* GPU-init failure during load → CPU retry, real load errors still raised
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import ClassVar

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai.models.gpu_runtime import (
    GPU_LAYER_MAGIC_FULL,
    ExecutionMode,
    GPUCapabilities,
    GPUStrategy,
    decide_gpu_layers,
    estimate_model_vram_bytes,
    register_cuda_dll_dir,
)

GB = 1024**3

# Deterministic fixtures for the RTX 3080 class (10 GB) and model sizes.
VRAM_10GB = 10 * GB
MODEL_14GB = 14 * GB   # Qwen3-Coder-30B-A3B-class quantized model
MODEL_4GB = 4 * GB     # small model that fits comfortably
MODEL_7GB = 7 * GB     # mid model (7B Q4 with mmproj room)

GPU_OK_10GB = GPUCapabilities(
    offload_supported=True, vram_bytes=VRAM_10GB, vram_source="nvml"
)
GPU_UNKNOWN_VRAM = GPUCapabilities(
    offload_supported=True, vram_bytes=0, vram_source="nvml-missing"
)
CPU_ONLY_CAPS = GPUCapabilities(
    offload_supported=False, vram_bytes=0, vram_source="llama-cpu-build-or-missing"
)


# --------------------------------------------------------------------------- #
# Strategy selection
# --------------------------------------------------------------------------- #


class TestStrategySelection:
    def test_cpu_only_environment(self):
        """Case A: no capable GPU → CPU_ONLY."""
        decision = decide_gpu_layers(
            model_size_bytes=MODEL_4GB,
            n_ctx=4096,
            capabilities=CPU_ONLY_CAPS,
            mode=ExecutionMode.AUTO,
        )
        assert decision.strategy is GPUStrategy.CPU_ONLY
        assert decision.n_gpu_layers == 0

    def test_llama_cpu_only_build(self):
        """Case B: CPU-only llama.cpp build → CPU_ONLY even with model present."""
        decision = decide_gpu_layers(
            model_size_bytes=MODEL_4GB,
            n_ctx=4096,
            capabilities=GPUCapabilities(offload_supported=False, vram_bytes=VRAM_10GB),
        )
        assert decision.strategy is GPUStrategy.CPU_ONLY
        assert decision.n_gpu_layers == 0

    def test_forced_cpu_mode(self):
        """User-forced CPU wins over capable GPU."""
        decision = decide_gpu_layers(
            model_size_bytes=MODEL_4GB,
            n_ctx=4096,
            capabilities=GPU_OK_10GB,
            mode=ExecutionMode.CPU,
        )
        assert decision.strategy is GPUStrategy.CPU_ONLY
        assert decision.n_gpu_layers == 0

    def test_small_model_fits_full_gpu(self):
        """Case E: comfortable fit → FULL_GPU candidate."""
        decision = decide_gpu_layers(
            model_size_bytes=MODEL_4GB,
            n_ctx=4096,
            capabilities=GPU_OK_10GB,
        )
        assert decision.strategy is GPUStrategy.FULL_GPU
        assert decision.n_gpu_layers == GPU_LAYER_MAGIC_FULL

    def test_model_exceeding_vram_not_full_gpu(self):
        """Case F / RTX 3080 case 20: ~14 GB model on 10 GB VRAM → never auto
        FULL_GPU."""
        decision = decide_gpu_layers(
            model_size_bytes=MODEL_14GB,
            n_ctx=4096,
            capabilities=GPU_OK_10GB,
        )
        assert decision.strategy is not GPUStrategy.FULL_GPU
        assert decision.n_gpu_layers != GPU_LAYER_MAGIC_FULL
        assert decision.n_gpu_layers == 0  # exceeds total VRAM → CPU

    def test_partial_offload_selected_between_budgets(self):
        """Case F: a model larger than the safe budget but under total VRAM
        gets a bounded PARTIAL_GPU share (7.5 GB model on 10 GB VRAM:
        estimate ~8.9 GB > 8.5 GB budget, but < 10 GB total)."""
        decision = decide_gpu_layers(
            model_size_bytes=int(7.5 * GB),
            n_ctx=4096,
            capabilities=GPU_OK_10GB,
        )
        assert decision.strategy is GPUStrategy.PARTIAL_GPU
        assert 0 < decision.n_gpu_layers < GPU_LAYER_MAGIC_FULL

    def test_999_never_universal(self):
        """The magic full-offload value is only chosen for a comfortable
        fit — never for unknown VRAM or oversized models."""
        for size in (MODEL_14GB, 20 * GB, 30 * GB):
            decision = decide_gpu_layers(
                model_size_bytes=size,
                n_ctx=4096,
                capabilities=GPU_OK_10GB,
            )
            assert decision.n_gpu_layers != GPU_LAYER_MAGIC_FULL

    def test_vram_unknown_conservative_cpu(self):
        """Case C: GPU detected but VRAM unavailable → conservative, no
        crash, no blind full offload."""
        decision = decide_gpu_layers(
            model_size_bytes=MODEL_4GB,
            n_ctx=4096,
            capabilities=GPU_UNKNOWN_VRAM,
        )
        assert decision.strategy is GPUStrategy.CPU_ONLY
        assert decision.n_gpu_layers == 0
        assert "unknown" in decision.reason.lower()

    def test_model_size_unknown_cpu(self):
        decision = decide_gpu_layers(
            model_size_bytes=0,
            n_ctx=4096,
            capabilities=GPU_OK_10GB,
        )
        assert decision.strategy is GPUStrategy.CPU_ONLY

    def test_context_length_increases_estimate(self):
        """KV cache considerations: larger context → larger estimate."""
        small_ctx = estimate_model_vram_bytes(MODEL_4GB, 1024)
        large_ctx = estimate_model_vram_bytes(MODEL_4GB, 65536)
        assert large_ctx > small_ctx
        # And a big context can flip a fitting model into partial.
        fit_small = decide_gpu_layers(
            model_size_bytes=MODEL_7GB, n_ctx=2048, capabilities=GPU_OK_10GB
        )
        fit_large = decide_gpu_layers(
            model_size_bytes=MODEL_7GB, n_ctx=32768, capabilities=GPU_OK_10GB
        )
        assert fit_small.strategy is GPUStrategy.FULL_GPU
        assert fit_large.strategy is not GPUStrategy.FULL_GPU

    def test_conservative_vram_reserve(self):
        """Test 12: the safe budget is total VRAM minus the reserve — a model
        that fits total VRAM but not the budget must not be FULL_GPU."""
        # 10 GB VRAM, reserve 15% → budget 8.5 GB.  A ~9 GB model fits
        # total but not the budget.
        decision = decide_gpu_layers(
            model_size_bytes=9 * GB,
            n_ctx=4096,
            capabilities=GPU_OK_10GB,
        )
        assert decision.strategy is not GPUStrategy.FULL_GPU

    def test_partial_share_scales_with_budget(self):
        """More headroom → more layers offloaded (bounded)."""
        tight = decide_gpu_layers(
            model_size_bytes=int(7.5 * GB), n_ctx=4096, capabilities=GPU_OK_10GB
        )
        roomy = decide_gpu_layers(
            model_size_bytes=int(7.5 * GB),
            n_ctx=4096,
            capabilities=GPUCapabilities(
                offload_supported=True, vram_bytes=12 * GB, vram_source="nvml"
            ),
        )
        assert tight.strategy is GPUStrategy.PARTIAL_GPU
        assert roomy.n_gpu_layers > tight.n_gpu_layers

    def test_reason_is_human_readable(self):
        decision = decide_gpu_layers(
            model_size_bytes=MODEL_4GB, n_ctx=4096, capabilities=GPU_OK_10GB
        )
        assert "GB" in decision.reason
        assert decision.reason


# --------------------------------------------------------------------------- #
# Manual override (expert behaviour)
# --------------------------------------------------------------------------- #


class TestManualOverride:
    def test_manual_layers_honoured_on_capable_gpu(self):
        decision = decide_gpu_layers(
            model_size_bytes=MODEL_14GB,
            n_ctx=4096,
            capabilities=GPU_OK_10GB,
            manual_layers=20,
        )
        assert decision.n_gpu_layers == 20
        assert "expert" in decision.reason.lower()

    def test_manual_override_rejected_without_offload_support(self):
        """The override is expert sizing, not a bypass of hard limits."""
        decision = decide_gpu_layers(
            model_size_bytes=MODEL_14GB,
            n_ctx=4096,
            capabilities=CPU_ONLY_CAPS,
            manual_layers=99,
        )
        assert decision.n_gpu_layers == 0
        assert decision.strategy is GPUStrategy.CPU_ONLY

    def test_manual_override_rejected_in_cpu_mode(self):
        decision = decide_gpu_layers(
            model_size_bytes=MODEL_4GB,
            n_ctx=4096,
            capabilities=GPU_OK_10GB,
            mode=ExecutionMode.CPU,
            manual_layers=99,
        )
        assert decision.n_gpu_layers == 0


# --------------------------------------------------------------------------- #
# Capability detection (NVML safety) — deterministic fakes
# --------------------------------------------------------------------------- #


class FakeNvmlModule:
    """Deterministic pynvml stand-in."""

    def __init__(self, vram_bytes: int = VRAM_10GB, fail_init: bool = False):
        self._vram = vram_bytes
        self._fail_init = fail_init
        self.init_calls = 0
        self.shutdown_calls = 0

    def nvmlInit(self):
        self.init_calls += 1
        if self._fail_init:
            raise RuntimeError("NVML: driver not loaded")

    def nvmlShutdown(self):
        self.shutdown_calls += 1

    def nvmlDeviceGetHandleByIndex(self, index):
        return ("fake-handle", index)

    def nvmlDeviceGetMemoryInfo(self, handle):
        class _Info:
            total = self._vram

        return _Info()


class TestNvmlSafety:
    def _detect(self, monkeypatch, fake, llama_offload):
        import ai.models.gpu_runtime as rt

        # NOTE: in-place setitem on the REAL sys.modules dict — replacing
        # sys.modules wholesale does not affect the ``import pynvml``
        # statement inside _read_vram_via_nvml when a real pynvml was
        # already imported by an earlier test module (the C-import fast
        # path bypasses the replaced dict).  setitem patches the actual
        # mapping the import system consults.
        monkeypatch.setitem(sys.modules, "pynvml", fake)
        monkeypatch.setattr(
            rt, "_llama_supports_offload", lambda: llama_offload
        )
        monkeypatch.setattr(rt, "_capabilities_cache", None, raising=False)
        monkeypatch.setattr(rt, "apply_cuda_dll_discovery", list)
        return rt.detect_gpu_capabilities(refresh=True)

    def test_known_vram_value(self, monkeypatch):
        caps = self._detect(monkeypatch, FakeNvmlModule(VRAM_10GB), True)
        assert caps.offload_supported
        assert caps.vram_bytes == VRAM_10GB
        assert caps.vram_source == "nvml"

    def test_nvml_missing(self, monkeypatch):
        """Test 5: missing pynvml → safe zero-VRAM capability, no crash."""
        import ai.models.gpu_runtime as rt

        monkeypatch.setitem(sys.modules, "pynvml", None)  # find_spec-kill
        monkeypatch.setattr(
            rt, "_llama_supports_offload", lambda: True
        )
        monkeypatch.setattr(rt, "_capabilities_cache", None, raising=False)
        monkeypatch.setattr(rt, "apply_cuda_dll_discovery", list)
        caps = rt.detect_gpu_capabilities(refresh=True)
        assert caps.vram_bytes == 0
        assert not caps.vram_known

    def test_nvml_init_failure(self, monkeypatch):
        """Test 6: nvmlInit failing (driver/permissions) → safe fallback."""
        caps = self._detect(monkeypatch, FakeNvmlModule(fail_init=True), True)
        assert caps.offload_supported
        assert caps.vram_bytes == 0
        assert caps.warnings

    def test_nvml_shutdown_called(self, monkeypatch):
        fake = FakeNvmlModule()
        self._detect(monkeypatch, fake, True)
        assert fake.init_calls == 1
        assert fake.shutdown_calls >= 1

    def test_llama_cpu_build_skips_vram(self, monkeypatch):
        """CPU-only llama.cpp short-circuits NVML entirely."""
        fake = FakeNvmlModule()
        caps = self._detect(monkeypatch, fake, llama_offload=False)
        assert caps.offload_supported is False
        assert fake.init_calls == 0

    def test_llama_cpp_missing_is_cpu(self, monkeypatch):
        """Backend reports no offload → capability must be CPU-only,
        regardless of whether a real llama_cpp exists in this env (the
        full-suite run may have it imported from a prior test module)."""
        import ai.models.gpu_runtime as rt

        monkeypatch.setattr(rt, "_capabilities_cache", None, raising=False)
        monkeypatch.setattr(rt, "apply_cuda_dll_discovery", list)
        monkeypatch.setattr(
            rt, "_llama_supports_offload", lambda: False
        )
        caps = rt.detect_gpu_capabilities(refresh=True)
        assert caps.offload_supported is False


# --------------------------------------------------------------------------- #
# CUDA DLL discovery (not sys.path-only)
# --------------------------------------------------------------------------- #


class TestCudaDllDiscovery:
    def test_explicit_registration_extension_point(self, tmp_path, monkeypatch):
        """register_cuda_dll_dir (the PHASE 5 hook) is honoured without
        any sys.path involvement."""
        import ai.models.gpu_runtime as rt

        dll_dir = tmp_path / "bundle" / "cuda_bin"
        dll_dir.mkdir(parents=True)
        monkeypatch.setattr(rt, "_extra_dll_dirs", [])
        monkeypatch.setattr(rt, "_candidate_nvidia_roots", list)

        resolved = register_cuda_dll_dir(dll_dir)
        assert resolved == dll_dir.resolve()
        assert dll_dir.resolve() in rt.discover_cuda_dll_dirs()

    def test_registration_ignores_relative(self, tmp_path, monkeypatch):
        import ai.models.gpu_runtime as rt

        monkeypatch.setattr(rt, "_extra_dll_dirs", [])
        # Environment isolation: a dev env WITH nvidia wheels installed
        # would otherwise contribute real site-packages dirs and break
        # the empty-result expectation.
        monkeypatch.setattr(rt, "_candidate_nvidia_roots", lambda: [])
        assert register_cuda_dll_dir("relative_cuda") is None
        assert rt.discover_cuda_dll_dirs() == []

    def test_registration_ignores_missing(self, tmp_path, monkeypatch):
        import ai.models.gpu_runtime as rt

        monkeypatch.setattr(rt, "_extra_dll_dirs", [])
        monkeypatch.setattr(rt, "_candidate_nvidia_roots", lambda: [])
        missing = tmp_path / "no_such_dir"
        assert register_cuda_dll_dir(missing) is None

    def test_sysconfig_source_independent_of_sys_path(
        self, tmp_path, monkeypatch
    ):
        """nvidia package roots are found via the import system/sysconfig
        even when sys.path contains nothing relevant."""
        import ai.models.gpu_runtime as rt

        nvidia_root = tmp_path / "site-pure" / "nvidia"
        cuda_bin = nvidia_root / "cublas" / "bin"
        cuda_bin.mkdir(parents=True)

        def fake_sysconfig_roots():
            return [nvidia_root]

        monkeypatch.setattr(rt, "_extra_dll_dirs", [])
        monkeypatch.setattr(rt, "_candidate_nvidia_roots", fake_sysconfig_roots)
        dirs = rt.discover_cuda_dll_dirs()
        assert cuda_bin.resolve() in [d.resolve() for d in dirs]

    def test_no_hardcoded_developer_cuda_path(self):
        """Test 19: no developer-machine CUDA Toolkit path anywhere in the
        runtime module."""
        source = (
            Path(__file__).resolve().parents[1] / "ai" / "models" / "gpu_runtime.py"
        ).read_text(encoding="utf-8")
        banned = (
            "C:\\\\Program Files\\\\NVIDIA",
            "Program Files/NVIDIA",
            "NVIDIA GPU Computing Toolkit",
            "E:\\\\cuda",
        )
        for needle in banned:
            assert needle.lower() not in source.lower()

    def test_apply_safe_without_cuda(self, monkeypatch):
        """Test 16: applying discovery with no CUDA present is a safe no-op."""
        import ai.models.gpu_runtime as rt

        monkeypatch.setattr(rt, "_extra_dll_dirs", [])
        monkeypatch.setattr(rt, "_candidate_nvidia_roots", list)
        monkeypatch.setattr(rt, "_applied_dll_dirs", [])
        applied = rt.apply_cuda_dll_discovery()
        assert applied == []


# --------------------------------------------------------------------------- #
# Loader integration (model-aware decision at load time)
# --------------------------------------------------------------------------- #


class _FakeLlama:
    """Deterministic llama_cpp.Llama stand-in."""

    instances: ClassVar[list[_FakeLlama]] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False
        _FakeLlama.instances.append(self)

    def close(self):
        self.closed = True


class TestLoaderIntegration:
    @pytest.fixture()
    def loader_env(self, monkeypatch, tmp_path):
        """Isolated GGUFModelLoader with faked llama_cpp + capabilities."""
        import ai.models.gpu_runtime as rt
        import ai.models.model_loader as ml

        fake_module = type(sys)("llama_cpp")
        fake_module.Llama = _FakeLlama
        monkeypatch.setitem(sys.modules, "llama_cpp", fake_module)
        monkeypatch.setattr(
            rt, "_capabilities_cache", GPU_OK_10GB, raising=False
        )
        model_file = tmp_path / "big-model.gguf"
        model_file.write_bytes(b"0" * 8)  # tiny placeholder; size from stat
        return ml, rt, model_file

    def test_load_uses_model_aware_strategy(self, loader_env, monkeypatch):
        """A model larger than VRAM must NOT be loaded with the universal
        full-offload value — the loader consults the centralized decision
        with the REAL file size (mocked 14 GB here to prove plumbing)."""
        ml, _rt, model_file = loader_env
        _FakeLlama.instances.clear()

        original_stat = Path.stat

        def fake_stat(self, **kwargs):
            if self == model_file:
                class _S:
                    st_size = 14 * GB

                return _S()
            return original_stat(self, **kwargs)

        monkeypatch.setattr(Path, "stat", fake_stat)
        loader = ml.GGUFModelLoader(n_ctx=4096, auto_gpu_layers=True)
        loader.load(model_file)
        assert loader.n_gpu_layers == 0
        assert loader._model.kwargs["n_gpu_layers"] == 0
        assert "exceeds total VRAM" in loader._gpu_reason

    def test_gpu_failure_falls_back_to_cpu(self, monkeypatch, tmp_path):
        """Test 17: GPU init failure during load → CPU retry; genuine CPU
        failure still raises a real error."""
        ml = __import__(
            "ai.models.model_loader", fromlist=["GGUFModelLoader"]
        )
        import ai.models.gpu_runtime as rt

        calls: list[dict] = []

        class _FailingLlama:
            def __init__(self, **kwargs):
                calls.append(kwargs)
                if kwargs.get("n_gpu_layers", 0) > 0:
                    raise RuntimeError(
                        "CUDA error: out of memory on device 0"
                    )
                raise RuntimeError("model file is corrupt")

        fake_module = type(sys)("llama_cpp")
        fake_module.Llama = _FailingLlama
        monkeypatch.setitem(sys.modules, "llama_cpp", fake_module)
        monkeypatch.setattr(
            rt, "_capabilities_cache", GPU_OK_10GB, raising=False
        )

        model_file = tmp_path / "m.gguf"
        model_file.write_bytes(b"GGUF")

        original_stat = Path.stat

        def fake_stat(self, **kwargs):
            if self == model_file:
                class _S:
                    st_size = 4 * GB

                return _S()
            return original_stat(self, **kwargs)

        monkeypatch.setattr(Path, "stat", fake_stat)
        loader = ml.GGUFModelLoader(n_ctx=4096, auto_gpu_layers=True)
        with pytest.raises(RuntimeError, match="corrupt"):
            loader.load(model_file)
        # GPU attempt happened first, then the CPU retry.
        assert calls[0]["n_gpu_layers"] == GPU_LAYER_MAGIC_FULL
        assert calls[1]["n_gpu_layers"] == 0

    def test_gpu_failure_cpu_retry_succeeds(self, monkeypatch, tmp_path):
        """GPU fails, CPU retry succeeds → model loaded, no crash, layers 0."""
        ml = __import__(
            "ai.models.model_loader", fromlist=["GGUFModelLoader"]
        )
        import ai.models.gpu_runtime as rt

        class _Llama:
            def __init__(self, **kwargs):
                if kwargs.get("n_gpu_layers", 0) > 0:
                    raise RuntimeError("CUDA error: insufficient VRAM")
                self.kwargs = kwargs

        fake_module = type(sys)("llama_cpp")
        fake_module.Llama = _Llama
        monkeypatch.setitem(sys.modules, "llama_cpp", fake_module)
        monkeypatch.setattr(
            rt, "_capabilities_cache", GPU_OK_10GB, raising=False
        )

        model_file = tmp_path / "small.gguf"
        model_file.write_bytes(b"GGUF")

        original_stat = Path.stat

        def fake_stat(self, **kwargs):
            if self == model_file:
                class _S:
                    st_size = 4 * GB

                return _S()
            return original_stat(self, **kwargs)

        monkeypatch.setattr(Path, "stat", fake_stat)
        loader = ml.GGUFModelLoader(n_ctx=4096, auto_gpu_layers=True)
        loader.load(model_file)
        assert loader.n_gpu_layers == 0
        assert loader._model is not None
        assert "CPU" in loader._gpu_reason or "cpu" in loader._gpu_reason

    def test_existing_cpu_configuration_unchanged(self, loader_env):
        """Test 18: default CPU behaviour (auto off, no override) → 0 layers."""
        ml, _rt, model_file = loader_env
        loader = ml.GGUFModelLoader(
            n_ctx=2048, auto_gpu_layers=False, n_gpu_layers=0
        )
        loader.load(model_file)
        # auto off + 0 override → CPU path (or legacy manual 0 preserved).
        assert loader.n_gpu_layers == 0

    def test_manual_expert_layers_reach_llama(self, loader_env):
        ml, _rt, model_file = loader_env
        loader = ml.GGUFModelLoader(
            n_ctx=2048, auto_gpu_layers=True, n_gpu_layers=24
        )
        loader.load(model_file)
        assert loader.n_gpu_layers == 24
        assert any(i.kwargs["n_gpu_layers"] == 24 for i in _FakeLlama.instances)


# --------------------------------------------------------------------------- #
# Estimator sanity
# --------------------------------------------------------------------------- #


class TestEstimator:
    def test_estimate_positive_and_monotonic(self):
        assert estimate_model_vram_bytes(0, 4096) == 0
        assert estimate_model_vram_bytes(-5, 4096) == 0
        assert estimate_model_vram_bytes(4 * GB, 4096) > 4 * GB
        assert (
            estimate_model_vram_bytes(4 * GB, 4096)
            < estimate_model_vram_bytes(8 * GB, 4096)
        )

    def test_file_size_is_lower_bound(self):
        """The estimate never pretends the file is smaller than it is."""
        assert estimate_model_vram_bytes(4 * GB, 4096) >= 4 * GB

    def test_kv_allowance_present(self):
        base = estimate_model_vram_bytes(4 * GB, 0)
        with_ctx = estimate_model_vram_bytes(4 * GB, 8192)
        assert with_ctx == base + 8192 * 64 * 1024
