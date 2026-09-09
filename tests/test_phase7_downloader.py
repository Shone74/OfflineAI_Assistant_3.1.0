"""PHASE 7 regression tests — hardware detection / model downloader.

All tests run WITHOUT: real GPU hardware, CUDA, pynvml, faster-whisper,
internet access, or multi-GB downloads.  Network behavior is tested
with mocks; disk layouts use tmp_path; hardware snapshots are injected
as deterministic fakes.

Covers (per phase plan):
1.  CPU/RAM detection fallbacks
2.  GPU detection when pynvml is unavailable (via Phase 4 caps)
3.  GPU VRAM unknown behavior
4.  WMI AdapterRAM unreliable/missing behavior (vendor hint only)
5.  Disk-space calculation against the actual models root
6.  Recommendation: comfortable GPU fit / partial GPU / too large for
    GPU / CPU-only machine / insufficient RAM / insufficient disk
7.  Canonical models.storage_root usage in the downloader
8.  Category placement (llm/embedding/stt)
9.  No fixed drive/path assumptions
10. Path traversal rejection
11. Symlink/junction escape rejection
12. Streaming download (chunked writes)
13. Progress reporting
14. HTTP failure handling
15. Interrupted download handling (no falsely-complete file)
16. Resume behavior (Range honored / rejected)
17. Expected-size validation
18. SHA-256 validation
19. SHA mismatch cleanup/failure
20. Existing valid file not unnecessarily overwritten
21. Insufficient disk space prevents download
22. Cancellation does not produce a falsely complete model
23. Downloader never writes outside the selected models root
24. UI/backend download work does not run synchronously on the Qt thread
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai.hardware import (
    HardwareSnapshot,
    free_disk_bytes_for_root,
)
from ai.models.recommendation import (
    DISK_SAFETY_MARGIN_BYTES,
    ModelRequirements,
    ModelVerdict,
    evaluate_model_fit,
)
from core import paths
from installer.catalog import CATALOG, DownloadableModel, get_catalog, is_installed
from installer.downloader import (
    PART_SUFFIX,
    SecureModelDownloader,
    check_disk_space,
)

GB = 1024**3
MB = 1024**2


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture()
def models_root_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the canonical models-root env override at a temp root."""
    root = tmp_path / "AI" / "Models"
    monkeypatch.setenv(paths.MODELS_ROOT_ENV_VAR, str(root))
    return root


@pytest.fixture()
def settings_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate core.paths SETTINGS_FILE resolution to temp settings.json."""
    user_data = tmp_path / "user_data"
    settings = user_data / "config" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(paths, "SETTINGS_FILE", settings)
    return settings


def _hw(
    *,
    ram: int = 32 * GB,
    vram: int = 10 * GB,
    offload: bool = True,
    cuda: bool = True,
    disk_free: int | None = 200 * GB,
    cpu_cores: int = 8,
) -> HardwareSnapshot:
    """Deterministic hardware snapshot factory."""
    return HardwareSnapshot(
        cpu_name="Test CPU",
        cpu_cores=cpu_cores,
        cpu_threads=cpu_cores * 2,
        ram_total_bytes=ram,
        gpu_name="Test GPU",
        gpu_vendor="NVIDIA",
        vram_bytes=vram,
        gpu_offload_supported=offload,
        cuda_available=cuda,
        disk_free_bytes=disk_free,
    )


def _fake_response(
    data: bytes,
    *,
    status_code: int = 200,
    headers: dict | None = None,
    iter_chunk: int = 1024,
):
    """Build a mock requests.Response streaming *data*."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {"Content-Length": str(len(data))}
    buf = io.BytesIO(data)

    def _iter_content(chunk_size=1024, **_):
        while True:
            chunk = buf.read(chunk_size)
            if not chunk:
                break
            yield chunk

    resp.iter_content = _iter_content
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    resp.raise_for_status = MagicMock()
    return resp


# --------------------------------------------------------------------------- #
# A. Hardware detection fallbacks
# --------------------------------------------------------------------------- #


class TestHardwareDetectionFallbacks:
    def test_cpu_detection_fallback_when_psutil_fails(self):
        """psutil failure degrades to 1 core / 1 thread, never raises."""
        from ai.hardware import _detect_cpu_counts

        with patch("psutil.cpu_count", side_effect=RuntimeError("boom")):
            cores, threads = _detect_cpu_counts()
        assert cores == 1 and threads == 1

    def test_ram_detection_fallback(self):
        from ai.hardware import _detect_ram_bytes

        with patch("psutil.virtual_memory", side_effect=Exception("nope")):
            assert _detect_ram_bytes() == 0

    def test_gpu_name_probe_never_trusts_adapter_ram(self, settings_file):
        """WMI probe supplies name/vendor only — VRAM stays 0/unknown."""
        probe_calls: list = []

        def _fake_legacy_probe():
            probe_calls.append(1)
            # Real shape: (GPUBrand, name, vram_wmi_untrusted, cuda)
            from installer.hardware import GPUBrand

            return (GPUBrand.NVIDIA, "RTX 4090", 24.0, True)

        from ai.hardware import _detect_gpu_name_vendor

        with patch("installer.hardware._detect_gpu", side_effect=_fake_legacy_probe):
            name, vendor = _detect_gpu_name_vendor()
        assert name == "RTX 4090"
        assert vendor == "NVIDIA"
        # The snapshot ignores the WMI VRAM figure entirely: VRAM comes
        # from the Phase 4 NVML probe (verified in the snapshot test).
        assert probe_calls

    def test_gpu_name_probe_handles_wmi_failure(self):
        from ai.hardware import _detect_gpu_name_vendor

        with patch(
            "installer.hardware._detect_gpu",
            side_effect=RuntimeError("WMI down"),
        ):
            name, vendor = _detect_gpu_name_vendor()
        assert name == "" and vendor == ""

    def test_snapshot_uses_phase4_caps_for_vram(self, settings_file, models_root_env):
        """Snapshot VRAM comes from Phase 4 NVML probe, not WMI."""
        from ai.models.gpu_runtime import GPUCapabilities

        caps = GPUCapabilities(
            offload_supported=True, vram_bytes=10 * GB, vram_source="nvml"
        )
        with patch(
            "ai.models.gpu_runtime.detect_gpu_capabilities", return_value=caps
        ), patch(
            "installer.hardware._detect_gpu",
            return_value=("NVIDIA", "RTX 3080", 1.0, True),  # WMI lies: 1 GB
        ):
            snap = __import__("ai.hardware", fromlist=["detect_hardware_snapshot"]).detect_hardware_snapshot()
        assert snap.vram_bytes == 10 * GB  # NVML wins, WMI ignored
        assert snap.gpu_offload_supported is True

    def test_snapshot_vram_unknown_when_nvml_missing(self, settings_file, models_root_env):
        """pynvml unavailable -> VRAM unknown (0), warning, no crash."""
        from ai.models.gpu_runtime import GPUCapabilities

        caps = GPUCapabilities(offload_supported=True, vram_bytes=0,
                               vram_source="nvml-missing")
        with patch(
            "ai.models.gpu_runtime.detect_gpu_capabilities", return_value=caps
        ):
            import ai.hardware as hw

            snap = hw.detect_hardware_snapshot()
        assert snap.vram_bytes == 0
        assert not snap.vram_known
        assert any("VRAM" in w for w in snap.warnings)

    def test_snapshot_degrades_when_gpu_runtime_fails(self, settings_file, models_root_env):
        with patch(
            "ai.models.gpu_runtime.detect_gpu_capabilities",
            side_effect=ImportError("no llama"),
        ):
            import ai.hardware as hw

            snap = hw.detect_hardware_snapshot()
        assert snap.gpu_offload_supported is False
        assert any("detection failed" in w for w in snap.warnings)

    def test_snapshot_respects_canonical_models_root(self, settings_file, models_root_env):
        """Disk space measured on the MODELS ROOT drive, not '/'."""
        import ai.hardware as hw

        root = models_root_env
        root.mkdir(parents=True, exist_ok=True)
        with patch("psutil.disk_usage") as du:
            du.return_value = MagicMock(free=123 * GB, total=500 * GB)
            snap = hw.detect_hardware_snapshot(models_root=root)
        du.assert_called_once()
        assert du.call_args[0][0] == str(root)
        assert snap.disk_free_bytes == 123 * GB

    def test_disk_free_for_missing_root_uses_anchor(self, tmp_path):
        """A not-yet-existing root still measures its drive anchor."""
        missing = tmp_path / "not_created" / "deep"
        val = free_disk_bytes_for_root(missing)
        assert val is not None and val >= 0

    def test_disk_free_probe_failure_returns_none(self, tmp_path):
        with patch("psutil.disk_usage", side_effect=PermissionError("denied")):
            assert free_disk_bytes_for_root(tmp_path) is None


# --------------------------------------------------------------------------- #
# B. Recommendation logic
# --------------------------------------------------------------------------- #


class TestRecommendationLogic:
    def test_comfortable_gpu_fit_recommended(self):
        hw = _hw(vram=10 * GB, ram=32 * GB)
        rec = evaluate_model_fit(ModelRequirements(4 * GB, "llm", n_ctx=4096), hw)
        assert rec.verdict is ModelVerdict.RECOMMENDED
        assert rec.gpu_strategy is not None

    def test_partial_gpu_possible(self):
        # 8.4 GB model on 10 GB VRAM: est ~9.9 GB > 8.5 GB safe budget
        # but < 10 GB total -> partial offload band
        hw = _hw(vram=10 * GB, ram=32 * GB)
        rec = evaluate_model_fit(ModelRequirements(int(8.4 * GB), "llm", n_ctx=4096), hw)
        assert rec.verdict is ModelVerdict.POSSIBLE
        assert rec.gpu_strategy is not None

    def test_too_large_for_gpu_cpu_recommended(self):
        # 30 GB model on 10 GB VRAM -> Phase 4 says CPU_ONLY
        hw = _hw(vram=10 * GB, ram=64 * GB)
        rec = evaluate_model_fit(ModelRequirements(30 * GB, "llm", n_ctx=4096), hw)
        assert rec.verdict is ModelVerdict.CPU_RECOMMENDED

    def test_file_size_below_vram_is_not_automatic_fit(self):
        """Never claim fit just because raw file < VRAM (Phase 4 rule)."""
        hw = _hw(vram=8 * GB, ram=16 * GB)
        # 7.9 GB file with big ctx -> overhead + KV push it over budget
        rec = evaluate_model_fit(ModelRequirements(int(7.9 * GB), "llm", n_ctx=32768), hw)
        assert rec.verdict is not ModelVerdict.RECOMMENDED

    def test_cpu_only_environment(self):
        hw = _hw(vram=0, offload=False, cuda=False, ram=32 * GB)
        rec = evaluate_model_fit(ModelRequirements(4 * GB, "llm"), hw)
        assert rec.verdict is ModelVerdict.CPU_RECOMMENDED

    def test_forced_cpu_mode(self):
        hw = _hw(vram=24 * GB)
        rec = evaluate_model_fit(
            ModelRequirements(4 * GB, "llm"), hw, gpu_mode="cpu"
        )
        assert rec.verdict is ModelVerdict.CPU_RECOMMENDED

    def test_insufficient_ram_rejected(self):
        hw = _hw(ram=8 * GB, vram=0, offload=False)
        rec = evaluate_model_fit(ModelRequirements(14 * GB, "llm"), hw)
        assert rec.verdict is ModelVerdict.INSUFFICIENT_RESOURCES

    def test_insufficient_disk_rejected(self):
        # 4 GB download needs 4 GB + 512 MiB margin = 4.5 GB > 4.4 GB free
        hw = _hw(disk_free=int(4.4 * GB), ram=32 * GB, vram=10 * GB)
        rec = evaluate_model_fit(ModelRequirements(4 * GB, "llm"), hw)
        assert rec.verdict is ModelVerdict.INSUFFICIENT_DISK
        # and a comfortable margin passes
        hw_ok = _hw(disk_free=50 * GB)
        rec_ok = evaluate_model_fit(ModelRequirements(4 * GB, "llm"), hw_ok)
        assert rec_ok.verdict is not ModelVerdict.INSUFFICIENT_DISK

    def test_unknown_ram_is_unknown_verdict(self):
        hw = _hw(ram=0)
        rec = evaluate_model_fit(ModelRequirements(4 * GB, "llm"), hw)
        assert rec.verdict is ModelVerdict.UNKNOWN

    def test_embedding_category_is_cpu_path(self):
        hw = _hw(vram=10 * GB, offload=True)
        rec = evaluate_model_fit(ModelRequirements(700 * MB, "embedding"), hw)
        assert rec.verdict is ModelVerdict.CPU_RECOMMENDED

    def test_verdicts_deterministic(self):
        hw = _hw(vram=10 * GB)
        reqs = ModelRequirements(4 * GB, "llm", n_ctx=4096)
        a = evaluate_model_fit(reqs, hw)
        b = evaluate_model_fit(reqs, hw)
        assert a == b

    def test_disk_margin_not_counted_as_free(self):
        """Free == needed + margin - 1 must FAIL (margin enforced)."""
        size = 4 * GB
        hw = _hw(disk_free=size + DISK_SAFETY_MARGIN_BYTES - 1)
        rec = evaluate_model_fit(ModelRequirements(size, "llm"), hw)
        assert rec.verdict is ModelVerdict.INSUFFICIENT_DISK

    def test_stt_category_recommended_on_cpu(self):
        hw = _hw(ram=16 * GB, vram=0, offload=False)
        rec = evaluate_model_fit(ModelRequirements(500 * MB, "stt"), hw)
        assert rec.verdict is ModelVerdict.CPU_RECOMMENDED


# --------------------------------------------------------------------------- #
# C. Catalog
# --------------------------------------------------------------------------- #


class TestCatalog:
    def test_catalog_entries_have_valid_categories(self):
        for entry in get_catalog():
            assert entry.category in ("llm", "embedding", "stt")

    def test_catalog_filenames_are_bare(self):
        for entry in get_catalog():
            assert "/" not in entry.filename
            assert "\\" not in entry.filename
            assert ".." not in entry.filename

    def test_is_installed_physical_probe(self, tmp_path):
        # PHASE 9: use the fully curated STT entry — its exact size is
        # enforced by is_installed.  (Approximate entries fall back to
        # existence-only semantics, covered in Phase 9 tests.)
        entry = next(e for e in CATALOG if e.is_fully_curated)
        cat_dir = tmp_path / entry.category
        cat_dir.mkdir(parents=True)
        # Not installed yet
        assert is_installed(entry, tmp_path) is False
        # Wrong-size file -> not installed (exact metadata enforced)
        (cat_dir / entry.filename).write_bytes(b"\0" * min(entry.size_bytes - 1, 1024))
        assert is_installed(entry, tmp_path) is False
        # Exact-size file -> installed  (small stand-in payload: build a
        # synthetic curated entry so the real 484 MB file need not be written)
        import hashlib as _h

        from installer.catalog import DownloadableModel as _DM

        synthetic = _DM(
            model_id="llm/synthetic-curated", display_name="Synthetic",
            category="llm", url="https://example.com/s.gguf",
            filename="s.gguf", size_bytes=1024,
            sha256=_h.sha256(b"\0" * 1024).hexdigest(),
        )
        (tmp_path / "llm").mkdir(parents=True, exist_ok=True)
        (tmp_path / "llm" / "s.gguf").write_bytes(b"\0" * 1024)
        assert is_installed(synthetic, tmp_path) is True

    def test_companions_counted_in_total(self):
        for entry in get_catalog():
            expected = entry.size_bytes + sum(c.size_bytes for c in entry.companions)
            assert entry.total_download_bytes == expected

    def test_invalid_category_rejected(self):
        with pytest.raises(ValueError, match="category"):
            DownloadableModel(
                model_id="x", display_name="X", category="bogus",
                url="https://example.com/x.gguf", filename="x.gguf", size_bytes=1,
            )

    def test_invalid_filename_rejected(self):
        with pytest.raises(ValueError, match="filename"):
            DownloadableModel(
                model_id="x", display_name="X", category="llm",
                url="https://example.com", filename="../escape.gguf", size_bytes=1,
            )


# --------------------------------------------------------------------------- #
# D. Downloader — security
# --------------------------------------------------------------------------- #


class TestDownloaderSecurity:
    def test_traversal_filename_rejected(self, models_root_env):
        dl = SecureModelDownloader("llm")
        for bad in ("../evil.gguf", "..\\evil.gguf", "sub/dir/model.gguf",
                    "C:\\models\\evil.gguf", "/abs.gguf"):
            with pytest.raises(ValueError):
                dl.download("https://example.com/m.gguf", bad)

    def test_absolute_path_filename_rejected(self, models_root_env):
        with pytest.raises(ValueError):
            SecureModelDownloader("llm").download(
                "https://example.com/m.gguf", str(models_root_env / "evil.gguf")
            )

    def test_non_model_extension_rejected(self, models_root_env):
        dl = SecureModelDownloader("llm")
        with pytest.raises(ValueError):
            dl.download("https://example.com/x", "setup.exe")
        with pytest.raises(ValueError):
            dl.download("https://example.com/x", "run.bat")

    def test_bad_category_rejected(self, models_root_env):
        with pytest.raises(ValueError, match="category"):
            SecureModelDownloader("viruses")

    def test_relative_models_root_rejected(self):
        with pytest.raises(ValueError, match="absolute"):
            SecureModelDownloader("llm", models_root="relative/path")

    def test_destination_stays_in_category_dir(self, models_root_env, tmp_path):
        """The final path can never land outside <root>/<category>."""
        dl = SecureModelDownloader("llm")
        dest = dl._authorized_dest("model.gguf")
        assert dest.parent == models_root_env / "llm"

    def test_symlink_escape_rejected(self, models_root_env):
        """A symlink planted inside the category dir cannot redirect
        the download outside the models root."""
        import os

        cat_dir = models_root_env / "llm"
        cat_dir.mkdir(parents=True, exist_ok=True)
        outside = models_root_env.parent / "outside.gguf"
        link = cat_dir / "model.gguf"
        try:
            os.symlink(outside, link)
        except OSError:
            pytest.skip("symlinks unavailable on this system")
        dl = SecureModelDownloader("llm")
        with pytest.raises(ValueError, match="escape"):
            dl._authorized_dest("model.gguf")

    def test_downloader_never_writes_outside_root(self, models_root_env, tmp_path):
        """Streaming write goes only under the canonical root (mock net)."""
        data = b"GGUF" + b"x" * 4096
        dl = SecureModelDownloader("llm")
        with patch("requests.get", return_value=_fake_response(data)):
            result = dl.download("https://example.com/m.gguf", "model.gguf")
        assert result.success
        assert result.dest == models_root_env / "llm" / "model.gguf"
        assert result.dest.is_file()
        # No stray files anywhere else under tmp
        written = [p for p in tmp_path.rglob("*") if p.is_file()]
        assert all(models_root_env in p.parents for p in written)


# --------------------------------------------------------------------------- #
# E. Downloader — happy path / streaming / progress
# --------------------------------------------------------------------------- #


class TestDownloaderHappyPath:
    def test_streaming_download_writes_chunks(self, models_root_env):
        data = b"GGUF" + os.urandom(3 * 1024 * 1024)  # 3 MB, multi-chunk
        progress_events: list = []

        dl = SecureModelDownloader(
            "llm", chunk_size=256 * 1024,
            progress_callback=lambda p: progress_events.append(
                (p.bytes_downloaded, p.total_bytes, p.status.value)
            ),
        )
        with patch("requests.get", return_value=_fake_response(data)):
            result = dl.download("https://example.com/m.gguf", "model.gguf")

        assert result.success
        assert result.dest.read_bytes() == data
        assert result.size_bytes == len(data)
        # Streaming: multiple progress events, monotonic bytes
        assert len(progress_events) >= 3
        bytes_seq = [e[0] for e in progress_events]
        assert bytes_seq == sorted(bytes_seq)
        assert bytes_seq[-1] == len(data)

    def test_progress_reports_totals(self, models_root_env):
        data = b"GGUF" + b"y" * (1024 * 1024)
        events: list = []
        dl = SecureModelDownloader(
            "llm", progress_callback=lambda p: events.append(p)
        )
        with patch("requests.get", return_value=_fake_response(data)):
            dl.download("https://example.com/m.gguf", "model.gguf")
        assert events[0].total_bytes == len(data)
        assert events[-1].bytes_downloaded == len(data)

    def test_category_placement(self, models_root_env):
        """llm / embedding / stt files land in their category dirs."""
        for cat, fname in (("llm", "a.gguf"), ("embedding", "b.gguf"), ("stt", "c.bin")):
            dl = SecureModelDownloader(cat)
            data = b"GGUF" + b"z" * 128
            with patch("requests.get", return_value=_fake_response(data)):
                res = dl.download("https://example.com/x", fname)
            assert res.success
            assert res.dest.parent == models_root_env / cat

    def test_existing_valid_file_not_redownloaded(self, models_root_env):
        """A complete, size-matched model is never re-fetched."""
        data = b"GGUF" + b"k" * 2048
        dest = models_root_env / "llm" / "model.gguf"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

        fetch_calls: list = []
        def _no_fetch(*a, **kw):
            fetch_calls.append(a)
            raise AssertionError("network must not be touched")

        dl = SecureModelDownloader("llm")
        with patch("requests.get", side_effect=_no_fetch):
            result = dl.download(
                "https://example.com/m.gguf", "model.gguf",
                expected_size=len(data),
            )
        assert result.success
        assert result.dest.read_bytes() == data
        assert fetch_calls == []

    def test_existing_checksum_mismatch_replaced(self, models_root_env):
        """A corrupt existing file (sha mismatch) IS re-downloaded."""
        data = b"GGUF" + b"k" * 2048
        dest = models_root_env / "llm" / "model.gguf"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"CORRUPT" + b"k" * 2048)
        dl = SecureModelDownloader("llm")
        with patch("requests.get", return_value=_fake_response(data)):
            result = dl.download(
                "https://example.com/m.gguf", "model.gguf",
                expected_size=len(data),
                expected_sha256=hashlib.sha256(data).hexdigest(),
            )
        assert result.success
        assert result.dest.read_bytes() == data

    def test_companion_downloaded_sibling(self, models_root_env):
        """mmproj companions land next to the model (Phase 3 contract)."""
        from ai.models.download_service import download_entry
        from installer.catalog import CompanionFile

        # PHASE 9: entries with companions must be FULLY curated
        # (exact size + digest on every file) to pass the download
        # service gate — digests here match the mock payload bytes.
        entry = DownloadableModel(
            model_id="llm/test-vision", display_name="Test Vision",
            category="llm", url="https://example.com/model.gguf",
            filename="model.gguf", size_bytes=2048,
            sha256=hashlib.sha256(b"GGUF" + b"m" * 2044).hexdigest(),
            companions=(CompanionFile(
                filename="mmproj.gguf",
                url="https://example.com/mmproj.gguf",
                size_bytes=512,
                sha256=hashlib.sha256(b"GGUF" + b"p" * 508).hexdigest(),
            ),),
        )
        model_data = b"GGUF" + b"m" * 2044
        mmproj_data = b"GGUF" + b"p" * 508
        responses = iter([_fake_response(model_data), _fake_response(mmproj_data)])
        with patch("requests.get", side_effect=lambda *a, **k: next(responses)):
            primary, companions = download_entry(entry)
        assert primary.success
        assert len(companions) == 1 and companions[0].success
        cat = models_root_env / "llm"
        assert (cat / "model.gguf").read_bytes() == model_data
        assert (cat / "mmproj.gguf").read_bytes() == mmproj_data


# --------------------------------------------------------------------------- #
# F. Downloader — failures, interruption, resume, cancellation
# --------------------------------------------------------------------------- #


class TestDownloaderFailures:
    def _dl(self, root, **kw) -> SecureModelDownloader:
        return SecureModelDownloader("llm", **kw)

    def test_http_error_handled(self, models_root_env):
        import requests as _rq

        resp = MagicMock(status_code=404)
        resp.headers = {}
        resp.raise_for_status.side_effect = _rq.HTTPError("404 Not Found")
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        dl = SecureModelDownloader("llm", max_retries=2)
        with patch("requests.get", return_value=resp):
            result = dl.download("https://example.com/m.gguf", "model.gguf")
        assert not result.success
        assert "404" in (result.error or "") or "attempt" in (result.error or "")

    def test_interrupted_download_no_false_complete(self, models_root_env):
        """Network error mid-stream leaves ONLY a .part, never a model."""
        data = b"GGUF" + b"q" * (2 * 1024 * 1024)

        def _flaky(*a, **kw):
            resp = _fake_response(data)
            # Fail after first chunk: wrap generator
            original = resp.iter_content

            def dying_iter(chunk_size=1024, **_):
                first = True
                for chunk in original(chunk_size):
                    if not first:
                        raise ConnectionError("network died")
                    first = False
                    yield chunk

            resp.iter_content = dying_iter
            return resp

        dl = SecureModelDownloader("llm", chunk_size=1024 * 1024, max_retries=2)
        with patch("requests.get", side_effect=_flaky), patch(
            "requests.RequestException", ConnectionError
        ):
            # ConnectionError is not a requests.RequestException; the
            # downloader treats unexpected exceptions as failures too.
            result = dl.download("https://example.com/m.gguf", "model.gguf")

        dest = models_root_env / "llm" / "model.gguf"
        assert not result.success
        # EITHER a .part exists and no complete file, or everything clean —
        # never a falsely-complete model.
        assert not dest.exists()
        part = dest.with_name(dest.name + PART_SUFFIX)
        if part.exists():
            assert part.stat().st_size < len(data)

    def test_resume_with_range_support(self, models_root_env):
        """A .part file resumes when the server honors Range (206)."""
        full_data = b"GGUF" + b"r" * (2 * 1024 * 1024)
        dest = models_root_env / "llm" / "model.gguf"
        part = dest.with_name(dest.name + PART_SUFFIX)
        part.parent.mkdir(parents=True, exist_ok=True)
        prefix = full_data[:1024 * 1024]
        part.write_bytes(prefix)  # half downloaded earlier

        remaining = full_data[1024 * 1024:]
        resp206 = _fake_response(
            remaining, status_code=206,
            headers={"Content-Length": str(len(remaining)),
                     "Content-Range": f"bytes {len(prefix)}-{len(full_data)-1}/{len(full_data)}"},
        )
        dl = SecureModelDownloader("llm")
        with patch("requests.get", return_value=resp206) as mock_get:
            result = dl.download("https://example.com/m.gguf", "model.gguf")

        assert result.success
        assert result.dest.read_bytes() == full_data
        # Range header was requested
        assert mock_get.call_args.kwargs["headers"]["Range"] == f"bytes={len(prefix)}-"

    def test_resume_rejected_restarts_clean(self, models_root_env):
        """Server ignores Range (200) -> clean restart, no corruption."""
        full_data = b"GGUF" + b"s" * (1024 * 1024)
        dest = models_root_env / "llm" / "model.gguf"
        part = dest.with_name(dest.name + PART_SUFFIX)
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(b"GARBAGE_PREFIX")  # stale partial

        resp200 = _fake_response(full_data)  # ignores Range
        dl = SecureModelDownloader("llm")
        with patch("requests.get", return_value=resp200):
            result = dl.download("https://example.com/m.gguf", "model.gguf")

        assert result.success
        assert result.dest.read_bytes() == full_data  # no garbage prefix

    def test_size_validation_failure(self, models_root_env):
        data = b"GGUF" + b"t" * 1024
        dl = SecureModelDownloader("llm")
        with patch("requests.get", return_value=_fake_response(data)):
            result = dl.download(
                "https://example.com/m.gguf", "model.gguf",
                expected_size=999999,  # wrong expectation
            )
        assert not result.success
        assert "expected" in (result.error or "").lower()
        dest = models_root_env / "llm" / "model.gguf"
        assert not dest.exists()  # failed validation leaves no complete file

    def test_sha256_validation_success(self, models_root_env):
        data = b"GGUF" + b"u" * 4096
        digest = hashlib.sha256(data).hexdigest()
        dl = SecureModelDownloader("llm")
        with patch("requests.get", return_value=_fake_response(data)):
            result = dl.download(
                "https://example.com/m.gguf", "model.gguf",
                expected_sha256=digest,
            )
        assert result.success
        assert result.checksum_sha256 == digest

    def test_sha256_mismatch_cleanup(self, models_root_env):
        data = b"GGUF" + b"v" * 4096
        wrong = "0" * 64
        dl = SecureModelDownloader("llm")
        with patch("requests.get", return_value=_fake_response(data)):
            result = dl.download(
                "https://example.com/m.gguf", "model.gguf",
                expected_sha256=wrong,
            )
        assert not result.success
        assert "mismatch" in (result.error or "").lower()
        dest = models_root_env / "llm" / "model.gguf"
        part = dest.with_name(dest.name + PART_SUFFIX)
        assert not dest.exists()
        assert not part.exists()  # corrupt partial removed

    def test_cancellation_leaves_part_not_model(self, models_root_env):
        """Cancel mid-stream: .part remains resumable, no false model."""
        data = b"GGUF" + b"w" * (4 * 1024 * 1024)
        dl = SecureModelDownloader("llm", chunk_size=64 * 1024)

        def _cancel_after_first(*a, **kw):
            resp = _fake_response(data)
            original = resp.iter_content
            state = {"n": 0}

            def iter_then_cancel(chunk_size=1024, **_):
                for chunk in original(chunk_size):
                    state["n"] += 1
                    if state["n"] == 2:
                        dl.cancel()
                    yield chunk

            resp.iter_content = iter_then_cancel
            return resp

        with patch("requests.get", side_effect=_cancel_after_first):
            result = dl.download("https://example.com/m.gguf", "model.gguf")

        assert not result.success
        assert result.status.value == "cancelled"
        dest = models_root_env / "llm" / "model.gguf"
        part = dest.with_name(dest.name + PART_SUFFIX)
        assert not dest.exists()
        assert part.exists() and 0 < part.stat().st_size < len(data)
        # A canceled .part must NOT be discovered as a model
        from ai.models.discovery import discover_local_gguf

        found = discover_local_gguf(models_root_env / "llm")
        assert not any("model" in m.name for m in found)

    def test_disk_space_prevents_download(self, models_root_env):
        """Clearly insufficient space fails BEFORE fetching bytes."""
        data = b"GGUF" + b"x" * 1024

        def _no_fetch(*a, **kw):
            raise AssertionError("must not fetch when disk is full")

        dl = SecureModelDownloader("llm")
        with (
            patch("installer.downloader.check_disk_space",
                  return_value=(False, "Insufficient disk space")),
            patch("requests.get", side_effect=_no_fetch),
        ):
            result = dl.download(
                "https://example.com/m.gguf", "model.gguf",
                expected_size=len(data),
            )
        assert not result.success
        assert "disk" in (result.error or "").lower()

    def test_disk_check_targets_models_drive(self, models_root_env, tmp_path):
        """Free space is measured on the models root, not CWD/other dirs."""
        root = models_root_env
        root.mkdir(parents=True, exist_ok=True)
        with patch("psutil.disk_usage") as du:
            du.return_value = MagicMock(free=1 * GB)
            ok, reason = check_disk_space(root, 2 * GB)
        assert not ok
        assert reason is not None
        # Probe target IS the models root (that drive), not tmp_path/CWD
        assert Path(du.call_args[0][0]) == root

    def test_disk_check_unknown_passes(self, models_root_env):
        with patch("psutil.disk_usage", side_effect=PermissionError("x")):
            ok, reason = check_disk_space(models_root_env, 5 * GB)
        assert ok and reason is None


# --------------------------------------------------------------------------- #
# G. Canonical root / no fixed paths
# --------------------------------------------------------------------------- #


class TestCanonicalRootUsage:
    def test_downloader_uses_canonical_root(self, settings_file, models_root_env):
        dl = SecureModelDownloader("llm")
        assert dl.dest_dir == models_root_env / "llm"

    def test_no_fixed_drive_assumptions(self, settings_file):
        """Source contains no hardcoded developer model paths."""
        import ai.hardware as hwmod
        import installer.downloader as dlmod

        for source in (dlmod, hwmod):
            text = Path(source.__file__).read_text(encoding="utf-8")
            for banned in ("E:\\models", "C:\\AI", "D:\\OfflineAI",
                           "Program Files", "E:/models"):
                assert banned.lower() not in text.lower()

    def test_settings_root_wins_when_set(self, settings_file):
        root = settings_file.parent.parent.parent / "Elsewhere"
        settings_file.write_text(
            json.dumps({"models": {"storage_root": str(root)}}), encoding="utf-8"
        )
        assert paths.get_models_root() == root.resolve()
        dl = SecureModelDownloader("llm")
        assert dl.dest_dir == root.resolve() / "llm"

    def test_legacy_ai_models_dir_parent(self, settings_file):
        """Legacy ai.models_dir keeps resolving to its parent root."""
        legacy = settings_file.parent.parent.parent / "Old" / "llm"
        settings_file.write_text(
            json.dumps({"ai": {"models_dir": str(legacy)}}), encoding="utf-8"
        )
        assert paths.get_models_root() == legacy.parent.resolve()


# --------------------------------------------------------------------------- #
# H. Threading — downloads never run on the Qt UI thread
# --------------------------------------------------------------------------- #


class TestThreadingIntegration:
    def test_catalog_worker_is_qthread_offloading(self, qapp):
        """CatalogDownloadWorker runs downloads off the GUI thread."""
        from PySide6.QtCore import QThread

        from installer.catalog import find_model
        from ui.model_manager_dialog import CatalogDownloadWorker

        entry = find_model("llm/qwen3-4b-instruct-q4-k-m")
        assert entry is not None
        worker = CatalogDownloadWorker(entry)
        assert isinstance(worker, QThread)
        # run() executes download_entry which streams in the worker
        # thread — verified by monkeypatching download_entry with a
        # thread-identity probe.
        recorded: dict = {}
        import ai.models.download_service as svc

        orig = svc.download_entry

        def spy(*a, **kw):
            recorded["thread"] = threading.get_ident()
            return orig.__wrapped__ if hasattr(orig, "__wrapped__") else None

        with patch.object(svc, "download_entry", spy):
            worker.start()
            worker.wait(5000)
        main_thread = threading.get_ident()
        assert recorded.get("thread") not in (None, main_thread)
        assert recorded["thread"] != main_thread

    def test_dialog_downloads_run_in_worker_thread(self, qapp, models_root_env):
        """Full dialog path: start download -> work happens off-thread."""
        data = b"GGUF" + b"d" * 4096
        from unittest.mock import MagicMock as _MG

        from installer.catalog import find_model
        from ui.model_manager_dialog import (
            CatalogDownloadWorker,
            ModelManagerDialog,
        )

        manager = _MG()
        manager.list_models.return_value = []
        event_bus = _MG()
        dlg = ModelManagerDialog(manager, event_bus)

        entry = find_model("embedding/mxbai-embed-large-v1")
        worker_threads: list[int] = []
        progress_seen: list = []

        class _SpyWorker(CatalogDownloadWorker):
            def run(self) -> None:
                worker_threads.append(threading.get_ident())
                super().run()

        with patch("requests.get", return_value=_fake_response(data)):
            dlg._catalog_worker = _SpyWorker(entry)
            dlg._catalog_worker.progress.connect(
                lambda d, t, f: progress_seen.append(d)
            )
            dlg._catalog_worker.start()
            ok = dlg._catalog_worker.wait(10000)

        assert ok
        main_thread = threading.get_ident()
        assert worker_threads and worker_threads[0] != main_thread
        dlg.close()


# --------------------------------------------------------------------------- #
# I. Legacy compatibility
# --------------------------------------------------------------------------- #


class TestLegacyDownloaderCompat:
    def test_v1_class_exists_with_same_surface(self):
        from installer.downloader import (
            DownloadProgress,
            DownloadStatus,
            ModelDownloader,
        )

        dl = ModelDownloader()
        assert dl is not None
        assert DownloadStatus.COMPLETED.value == "completed"
        p = DownloadProgress(bytes_downloaded=1, total_bytes=2)
        assert p.bytes_downloaded == 1


# --------------------------------------------------------------------------- #
# J. Discovery ignores .part files
# --------------------------------------------------------------------------- #


class TestDiscoveryIgnoresPartFiles:
    def test_part_files_not_discovered_as_models(self, models_root_env):
        from ai.models.discovery import discover_extensionless_gguf

        cat = models_root_env / "llm"
        cat.mkdir(parents=True)
        # A .part file that happens to contain GGUF magic bytes
        (cat / "model.gguf.part").write_bytes(b"GGUF" + b"0" * 256)
        # A complete extensionless valid GGUF still discovered
        (cat / "realmodel").write_bytes(b"GGUF" + b"1" * 256)

        found = discover_extensionless_gguf(cat)
        names = [m.name for m in found]
        assert "realmodel" in names
        # No discovered entry may be the partial file.
        assert all(not m.name.startswith("model") for m in found)
        # And the .part file itself was skipped outright.
        assert all(".part" not in str(m.path) for m in found)


# --------------------------------------------------------------------------- #
# K. PHASE 10 Task 3 — cooperative cancellation wiring (H1/H2 regression)
# --------------------------------------------------------------------------- #


class _SlowCancelResponse:
    """Fake streaming response that cancels the download after N chunks.

    Reuses the _fake_response machinery but flips the downloader's
    cancel flag mid-stream — proving a cancel() from OUTSIDE the
    download thread takes effect at the next chunk boundary.
    """

    def __init__(self, data: bytes, cancel_target, after_chunks: int = 2):
        self._data = data
        self._cancel_target = cancel_target
        self._after = after_chunks

    def __call__(self, *a, **kw):
        resp = _fake_response(self._data)
        original = resp.iter_content
        state = {"n": 0}

        def iter_then_cancel(chunk_size=1024, **_):
            for chunk in original(chunk_size):
                state["n"] += 1
                if state["n"] == self._after:
                    self._cancel_target.cancel()
                yield chunk

        resp.iter_content = iter_then_cancel
        return resp


def _digest_matched_stt_entry():
    """Digest-matched STT catalog entry + exact payloads (Phase 9 e2e
    pattern): real catalog sizes, digests computed over our payloads so
    the strict size+SHA gates pass."""
    import dataclasses
    import hashlib as _hl

    from installer.catalog import find_model

    def _payload(size: int, seed: int) -> bytes:
        body = bytearray(b"GGUF-mock-payload")
        body.extend(bytes((i * seed) % 256 for i in range(256)) * (size // 256))
        body.extend(b"\x00" * (size - len(body)))
        return bytes(body)

    entry = find_model("stt/whisper-small")
    assert entry is not None and entry.is_fully_curated
    primary = _payload(entry.size_bytes, 1)
    companions = tuple(
        dataclasses.replace(
            c, sha256=_hl.sha256(_payload(c.size_bytes, 2)).hexdigest()
        )
        for c in entry.companions
    )
    mock_entry = dataclasses.replace(
        entry,
        sha256=_hl.sha256(primary).hexdigest(),
        companions=companions,
    )
    return mock_entry, primary, _payload


class TestCatalogWorkerCancellation:
    """H1: CatalogDownloadWorker.cancel() must reach the ACTIVE downloader."""

    def test_worker_cancel_reaches_active_downloader(self, qapp, models_root_env):
        """cancel() on the worker cancels the live downloader mid-stream:
        result is CANCELLED, final file not promoted, .part retained.

        This exercises the REAL production wiring: the worker builds
        the downloader via its own factory, the response stream calls
        ``worker.cancel()`` mid-flight (exactly what the GUI Cancel
        button / closeEvent do from the main thread), and the cancel
        must reach the ACTIVE downloader through the worker's live
        reference.
        """
        from ui.model_manager_dialog import CatalogDownloadWorker

        entry, primary, _payload = _digest_matched_stt_entry()
        worker = CatalogDownloadWorker(entry)
        results: list = []
        worker.finished.connect(lambda ok, path, err: results.append((ok, path, err)))

        with patch(
            "requests.get",
            side_effect=_SlowCancelResponse(primary, worker, after_chunks=2),
        ):
            worker.start()
            assert worker.wait(10000), "worker thread did not finish"
            # The finished signal is queued to the main thread — deliver
            # it before asserting on the recorded results.
            from PySide6.QtCore import QCoreApplication

            for _ in range(10):
                QCoreApplication.processEvents()

        assert worker._downloader is None, "stale downloader reference retained"
        assert results, "worker finished without emitting finished"
        ok, _path, err = results[0]
        assert ok is False
        assert "cancel" in (err or "").lower()

        # .part retained for resume, final file NOT promoted.
        digest_dir = models_root_env / "stt" / "whisper-small"
        part = digest_dir / "model.bin.part"
        assert part.exists(), "cancelled download must keep the .part file"
        assert not (digest_dir / "model.bin").exists()
        assert part.stat().st_size < entry.size_bytes

    def test_cancel_before_run_is_safe_noop(self):
        """cancel() without an active download is a harmless no-op."""
        from ui.model_manager_dialog import CatalogDownloadWorker

        entry, _primary, _payload = _digest_matched_stt_entry()
        worker = CatalogDownloadWorker(entry)
        worker.cancel()  # must not raise (no downloader yet)
        assert worker._downloader is None

    def test_download_entry_factory_receives_downloader(self, models_root_env):
        """download_entry(downloader_factory=...) uses the supplied
        downloader; callers without the argument keep current behavior."""
        from ai.models.download_service import download_entry
        from installer.downloader import SecureModelDownloader

        entry, primary, _payload = _digest_matched_stt_entry()
        created: list = []

        def factory(**kwargs):
            dl = SecureModelDownloader(**kwargs)
            created.append(dl)
            return dl

        responses = iter(
            [_fake_response(primary)]
            + [
                _fake_response(_payload(c.size_bytes, 2))
                for c in entry.companions
            ]
        )
        with patch("requests.get", side_effect=lambda *a, **k: next(responses)):
            primary_result, companions = download_entry(
                entry, downloader_factory=factory
            )

        assert created, "factory-built downloader was not used"
        assert primary_result.success, primary_result.error
        assert all(r.success for r in companions), [r.error for r in companions]
        # Default (no factory) path unchanged: the now-valid file
        # short-circuits without re-downloading (behavior preserved).
        with patch("requests.get", side_effect=AssertionError("must not re-download")):
            primary2, _ = download_entry(entry)
        assert primary2.success
        assert primary2.status.value == "completed"


class TestDialogClosePath:
    """H2: closeEvent uses cooperative cancel + bounded wait, no terminate()."""

    def test_close_event_contract_no_terminate(self):
        """Source contract: the Model Manager download close path never
        CALLS .terminate(); it cancels cooperatively with bounded waits."""
        import inspect

        from ui.model_manager_dialog import ModelManagerDialog

        source = inspect.getsource(ModelManagerDialog.closeEvent)
        # No terminate() CALL on the workers (prose may mention the word).
        assert ".terminate()" not in source
        # Both download workers are cancelled cooperatively...
        assert source.count("cancel()") == 2
        # ...and waited for with bounded waits (no unbounded wait()).
        assert "wait(5000)" in source
        assert ".wait()" not in source

    def test_legacy_download_worker_cancel_reaches_downloader(self, models_root_env):
        """H2: legacy DownloadWorker.cancel() propagates to the live
        v1 ModelDownloader (live forwarder, not a start-time snapshot)."""
        from installer.downloader import ModelDownloader

        data = b"GGUF" + b"l" * (2 * 1024 * 1024)

        def _cancel_wrapped(*a, **kw):
            # Response stream flips the wrapper's cancel flag mid-flight
            # — exactly what DownloadWorker.cancel() does via its held
            # reference.
            resp = _fake_response(data)
            original = resp.iter_content
            state = {"n": 0}

            def iter_then_cancel(chunk_size=1024, **_):
                for chunk in original(chunk_size):
                    state["n"] += 1
                    if state["n"] == 2:
                        wrapper_holder[0].cancel()
                    yield chunk

            resp.iter_content = iter_then_cancel
            return resp

        wrapper_holder: list = []
        dest = models_root_env / "llm"
        dest.mkdir(parents=True, exist_ok=True)
        wrapper = ModelDownloader(dest_dir=dest, chunk_size=64 * 1024)
        wrapper_holder.append(wrapper)

        with patch("requests.get", side_effect=_cancel_wrapped):
            result = wrapper.download(
                "https://example.com/legacy.gguf", "legacy.gguf"
            )

        assert not result.success
        assert result.status.value == "cancelled"
        part = dest / "legacy.gguf.part"
        assert part.exists()
        assert not (dest / "legacy.gguf").exists()

    def test_model_manager_download_model_factory_used(self, models_root_env):
        """ModelManager.download_model(downloader_factory=...) constructs
        the downloader through the factory (cancellable reference)."""
        from ai.models.model_manager import ModelManager

        created: list = []

        def factory(**kwargs):
            from installer.downloader import ModelDownloader

            dl = ModelDownloader(**kwargs)
            created.append(dl)
            return dl

        mm = ModelManager(models_dir=models_root_env / "llm")
        data = b"GGUF" + b"m" * 2048
        with patch("requests.get", return_value=_fake_response(data)):
            info = mm.download_model(
                "https://example.com/factory.gguf",
                "factory.gguf",
                downloader_factory=factory,
            )
        assert created, "factory downloader was not used"
        assert info.name
        # Default path (no factory) also still works.
        with patch("requests.get", return_value=_fake_response(data)):
            mm.download_model("https://example.com/plain.gguf", "plain.gguf")


class TestDialogCancelUIState:
    """Dialog Cancel button requests cancellation and UI returns to the
    non-downloading state."""

    def test_dialog_cancel_button_requests_cancel_and_worker_ends(self, qapp, models_root_env):
        from unittest.mock import MagicMock as _MG

        from ui.model_manager_dialog import CatalogDownloadWorker, ModelManagerDialog

        manager = _MG()
        manager.list_models.return_value = []
        event_bus = _MG()
        dlg = ModelManagerDialog(manager, event_bus)

        # Digest-matched entry so the primary passes the upfront size gate.
        entry, primary, _payload = _digest_matched_stt_entry()

        cancelled_calls: list = []
        finished_events: list = []

        class _CancellableWorker(CatalogDownloadWorker):
            def cancel(self):
                cancelled_calls.append(1)
                super().cancel()

        worker = _CancellableWorker(entry)
        dlg._catalog_worker = worker
        # Production wiring: the dialog's own handlers drive the button
        # and progress state (as _on_catalog_download connects them).
        worker.finished.connect(dlg._on_catalog_finished)
        worker.finished.connect(
            lambda ok, path, err: finished_events.append((ok, path, err))
        )
        dlg._btn_catalog_cancel.setEnabled(True)
        dlg._btn_catalog_download.setEnabled(False)
        dlg._catalog_progress.setVisible(True)

        # _on_catalog_finished shows a MODAL QMessageBox on failure —
        # patch it out (including during queued-signal delivery below)
        # or the offscreen test blocks forever on the cancellation branch.
        with patch("ui.model_manager_dialog.QMessageBox.critical"):
            with patch(
                "requests.get",
                side_effect=_SlowCancelResponse(primary, worker, after_chunks=2),
            ):
                worker.start()
                # Simulate the user pressing Cancel while the download is
                # streaming: the request propagates through the worker's
                # live downloader reference (production path).
                dlg._on_catalog_cancel()

            assert cancelled_calls, "_on_catalog_cancel did not request cancellation"
            # Worker either finished within the 3 s bound or already ended.
            assert worker.wait(5000), "worker did not finish after cancel"
            # Deliver the queued finished signal to the dialog handlers.
            from PySide6.QtCore import QCoreApplication

            for _ in range(20):
                QCoreApplication.processEvents()

        assert finished_events, "worker finished without emitting result"
        ok, _path, _err = finished_events[0]
        assert ok is False  # cancelled, not a success
        # UI restored to non-downloading state via _on_catalog_finished.
        assert dlg._btn_catalog_cancel.isEnabled() is False
        assert dlg._btn_catalog_download.isEnabled() is True
        assert dlg._catalog_progress.isVisible() is False
        dlg.close()
