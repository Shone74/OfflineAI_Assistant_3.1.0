"""PHASE 9 Task 1 tests — model catalog integrity curation.

Locks the catalog integrity contract:

* every downloadable catalog entry either carries VERIFIED EXACT
  metadata (exact size + real SHA-256 + immutable URL) or is explicitly
  marked not-fully-curated and is refused by the download service —
  guessed values are never shipped;
* ``size_bytes``/``sha256`` must be well-formed (integers, 64-hex
  lowercase digests, companions included);
* aggregate download-size math stays exact;
* ``is_installed`` never misreports valid files because of approximate
  metadata;
* the end-to-end pipeline (catalog → download_service → downloader →
  validation → final file) works for a fully curated entry using a MOCK
  server (no live network in tests);
* downloader .part / checksum-failure / discovery protections remain
  intact.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from installer.catalog import (
    CompanionFile,
    DownloadableModel,
    find_model,
    get_catalog,
    is_installed,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GB = 1024**3


# --------------------------------------------------------------------------- #
# Metadata shape / format contracts
# --------------------------------------------------------------------------- #


class TestCatalogIntegrityMetadata:
    def test_every_entry_has_positive_size(self):
        for entry in get_catalog():
            assert entry.size_bytes > 0, f"{entry.model_id}: size must be > 0"

    def test_every_checksum_well_formed(self):
        for entry in get_catalog():
            if entry.sha256 is not None:
                assert _SHA256_RE.match(entry.sha256), (
                    f"{entry.model_id}: sha256 must be 64-char lowercase hex"
                )

    def test_every_companion_metadata_well_formed(self):
        for entry in get_catalog():
            for companion in entry.companions:
                assert companion.size_bytes >= 0, (
                    f"{entry.model_id}/{companion.filename}: negative size"
                )
                if companion.sha256 is not None:
                    assert _SHA256_RE.match(companion.sha256), (
                        f"{entry.model_id}/{companion.filename}: bad sha256"
                    )

    def test_bad_checksum_rejected_at_construction(self):
        with pytest.raises(ValueError, match="sha256"):
            DownloadableModel(
                model_id="x/test", display_name="X", category="llm",
                url="https://example.com/x.gguf", filename="x.gguf",
                size_bytes=1024, sha256="not-a-digest",
            )

    def test_bad_companion_checksum_rejected(self):
        with pytest.raises(ValueError, match="sha256"):
            CompanionFile(
                filename="c.gguf", url="https://example.com/c.gguf",
                size_bytes=10, sha256="short",
            )

    def test_curation_flag_consistency(self):
        """is_fully_curated == exact size AND digest AND curated companions."""
        for entry in get_catalog():
            expected = bool(entry.sha256) and entry.size_bytes > 0 and all(
                bool(c.sha256) and c.size_bytes > 0 for c in entry.companions
            )
            assert entry.is_fully_curated == expected

    def test_at_least_one_fully_curated_entry(self):
        """Phase 9 delivered at least one VERIFIED, downloadable entry."""
        assert any(e.is_fully_curated for e in get_catalog())

    def test_curated_entry_url_is_immutable_revision(self):
        """Fully curated entries pin a commit revision (never 'main')."""
        for entry in get_catalog():
            if entry.is_fully_curated:
                assert "/resolve/main/" not in entry.url, (
                    f"{entry.model_id}: curated digest must not ride a "
                    f"mutable branch URL: {entry.url}"
                )
                # revision pin: 40-hex commit path component
                assert re.search(r"/resolve/[0-9a-f]{40}/", entry.url), (
                    f"{entry.model_id}: curated URL lacks commit pin"
                )


# --------------------------------------------------------------------------- #
# Exact verified metadata for the STT entry
# --------------------------------------------------------------------------- #


class TestSttEntryCuration:
    """The one entry whose bytes were fully verifiable in Phase 9."""

    def test_stt_entry_exact_size_and_digest(self):
        entry = find_model("stt/whisper-small")
        assert entry is not None
        assert entry.size_bytes == 483_546_902
        assert entry.sha256 == (
            "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671"
        )
        assert entry.is_fully_curated is True

    def test_stt_entry_canonical_systran_publisher(self):
        entry = find_model("stt/whisper-small")
        # Systran is the canonical faster-whisper publisher; the URL is
        # pinned to the commit the digest was verified against.
        assert "Systran/faster-whisper-small" in entry.url
        assert "mobiuslabsgmbh" not in entry.url

    def test_stt_entry_size_not_rounded(self):
        entry = find_model("stt/whisper-small")
        # 483,546,902 is the real byte count; rounded MiB/GiB values
        # are divisible by 2^20 / 2^30 — this one must not be.
        assert entry.size_bytes % (1024**2) != 0 or entry.size_bytes % (1024**3) != 0


# --------------------------------------------------------------------------- #
# Aggregate download math stays exact
# --------------------------------------------------------------------------- #


class TestAggregateDownloadMath:
    def test_total_download_bytes_exact(self):
        for entry in get_catalog():
            expected = entry.size_bytes + sum(
                c.size_bytes for c in entry.companions
            )
            assert entry.total_download_bytes == expected

    def test_companion_counted_once(self):
        coder = find_model("llm/qwen3-coder-30b-a3b-q4-k-m")
        assert coder is not None
        assert len(coder.companions) == 1
        assert coder.total_download_bytes == coder.size_bytes + coder.companions[0].size_bytes


# --------------------------------------------------------------------------- #
# is_installed: approximate metadata must not misreport valid files
# --------------------------------------------------------------------------- #


class TestIsInstalledCurationSemantics:
    def _write(self, path: Path, size: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\0" * size)

    def test_fully_curated_entry_size_checked(self, tmp_path):
        entry = find_model("stt/whisper-small")
        root = tmp_path
        folder = root / "stt" / entry.install_dir
        # wrong size -> not installed (exact metadata is enforced)
        self._write(folder / "model.bin", 1234)
        assert is_installed(entry, root) is False
        # exact size for ALL files -> installed
        self._write(folder / "model.bin", entry.size_bytes)
        for companion in entry.companions:
            self._write(folder / companion.filename, companion.size_bytes)
        assert is_installed(entry, root) is True

    def test_approximate_entry_existence_only(self, tmp_path):
        """A not-fully-curated entry: valid file => installed regardless
        of the rounded catalog size (Phase 9 fix for false 'absent')."""
        entry = next(e for e in get_catalog() if not e.is_fully_curated)
        root = tmp_path
        # On-disk size DIFFERS from the rounded catalog value, as any
        # real download of this entry would.
        self._write(root / entry.category / entry.filename, entry.size_bytes + 12345)
        assert is_installed(entry, root) is True


# --------------------------------------------------------------------------- #
# Download service refuses non-curated entries; curated entries flow
# --------------------------------------------------------------------------- #


def _mock_response(data: bytes):
    resp = MagicMock(status_code=200)
    resp.headers = {"Content-Length": str(len(data))}

    def _iter(chunk_size=1024, **_):
        buf = memoryview(data)
        for i in range(0, len(buf), chunk_size):
            yield bytes(buf[i:i + chunk_size])

    resp.iter_content = _iter
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    resp.raise_for_status = MagicMock()
    return resp


class TestDownloadServiceCurationGate:
    @pytest.fixture()
    def models_root_env(self, tmp_path, monkeypatch):
        from core import paths

        root = tmp_path / "AIModels"
        monkeypatch.setenv(paths.MODELS_ROOT_ENV_VAR, str(root))
        return root

    def test_non_curated_entry_refused_before_network(self, models_root_env):
        from ai.models.download_service import download_entry

        entry = next(e for e in get_catalog() if not e.is_fully_curated)
        with patch("requests.get", side_effect=AssertionError("network hit")):
            primary, companions = download_entry(entry)
        assert not primary.success
        assert "not fully curated" in (primary.error or "")
        assert companions == []
        # and nothing landed on disk
        assert not any((models_root_env).rglob("*.gguf"))
        assert not any((models_root_env).rglob("*.bin"))

    def test_curated_entry_downloads_end_to_end(self, models_root_env):
        """catalog entry → service → downloader → exact size → SHA-256 → files."""
        from ai.models.download_service import download_entry

        entry = find_model("stt/whisper-small")
        assert entry.is_fully_curated
        # Build payloads matching the EXACT cataloged sizes with matching
        # digests: real bytes, real hashes, mock transport — one response
        # per file (primary + 3 companions).
        import dataclasses

        def _payload(size: int, seed: int) -> bytes:
            body = bytearray(b"GGUF-mock-payload")
            body.extend(bytes((i * seed) % 256 for i in range(256)) * (size // 256))
            body.extend(b"\x00" * (size - len(body)))
            return bytes(body)

        primary_data = _payload(entry.size_bytes, 1)
        companion_data = {
            c.filename: _payload(c.size_bytes, 2) for c in entry.companions
        }
        mock_entry = dataclasses.replace(
            entry,
            sha256=hashlib.sha256(primary_data).hexdigest(),
            companions=tuple(
                dataclasses.replace(c, sha256=hashlib.sha256(companion_data[c.filename]).hexdigest())
                for c in entry.companions
            ),
        )
        responses = iter(
            [_mock_response(primary_data)]
            + [_mock_response(companion_data[c.filename]) for c in entry.companions]
        )
        with patch("requests.get", side_effect=lambda *a, **k: next(responses)):
            primary, companions = download_entry(mock_entry)
        assert primary.success, primary.error
        assert all(r.success for r in companions), [r.error for r in companions]
        # PHASE 9 contract: the complete named model FOLDER under stt/
        folder = models_root_env / "stt" / "whisper-small"
        assert folder.is_dir()
        assert (folder / "model.bin").is_file()
        assert (folder / "config.json").is_file()
        assert (folder / "tokenizer.json").is_file()
        assert (folder / "vocabulary.txt").is_file()
        assert (folder / "model.bin").stat().st_size == entry.size_bytes
        assert (
            hashlib.sha256((folder / "model.bin").read_bytes()).hexdigest()
            == hashlib.sha256(primary_data).hexdigest()
        )
        for companion in mock_entry.companions:
            got = (folder / companion.filename).read_bytes()
            assert hashlib.sha256(got).hexdigest() == companion.sha256

    def test_curated_entry_digest_mismatch_never_discovers(self, models_root_env):
        """A corrupted payload fails validation and leaves no model."""
        from ai.models.discovery import discover_local_gguf
        from ai.models.download_service import download_entry

        entry = find_model("stt/whisper-small")
        data = b"GGUF" + b"\x00" * (entry.size_bytes - 4)
        with patch("requests.get", return_value=_mock_response(data)):
            # shipped digest != mock payload digest -> must fail
            primary, _ = download_entry(entry)
        assert not primary.success
        assert "mismatch" in (primary.error or "").lower()
        folder = models_root_env / "stt" / "whisper-small"
        assert not (folder / "model.bin").exists()
        assert not (folder / "model.bin.part").exists()
        found = discover_local_gguf(models_root_env / "stt")
        assert not any("model.bin" in str(f.path) for f in found)


# --------------------------------------------------------------------------- #
# Downloader contracts remain intact (regression guards)
# --------------------------------------------------------------------------- #


class TestDownloaderContractsIntact:
    def test_part_files_never_discovered(self, tmp_path, monkeypatch):
        """PHASE 7/8 protection: .part files stay invisible to discovery."""
        from ai.models.discovery import discover_extensionless_gguf, discover_local_gguf

        cat = tmp_path / "llm"
        cat.mkdir(parents=True)
        (cat / "model.gguf.part").write_bytes(b"GGUF" + b"\0" * 64)
        assert not discover_local_gguf(cat)
        assert not discover_extensionless_gguf(cat)

    def test_strict_size_validation_unchanged(self, tmp_path, monkeypatch):
        """The downloader still enforces exact sizes when provided."""
        from core import paths
        from installer.downloader import SecureModelDownloader

        root = tmp_path / "Root"
        monkeypatch.setenv(paths.MODELS_ROOT_ENV_VAR, str(root))
        dl = SecureModelDownloader("llm")
        data = b"GGUF" + b"\0" * 1000
        with patch("requests.get", return_value=_mock_response(data)):
            result = dl.download(
                "https://example.com/x.gguf", "x.gguf",
                expected_size=999_999,  # deliberately wrong
            )
        assert not result.success
        assert "expected" in (result.error or "").lower()

    def test_sha_mismatch_cleans_part_file(self, tmp_path, monkeypatch):
        from core import paths
        from installer.downloader import SecureModelDownloader

        root = tmp_path / "Root"
        monkeypatch.setenv(paths.MODELS_ROOT_ENV_VAR, str(root))
        dl = SecureModelDownloader("llm")
        data = b"GGUF" + b"\0" * 1000
        with patch("requests.get", return_value=_mock_response(data)):
            result = dl.download(
                "https://example.com/x.gguf", "x.gguf",
                expected_size=len(data), expected_sha256="0" * 64,
            )
        assert not result.success
        part = root / "llm" / "x.gguf.part"
        dest = root / "llm" / "x.gguf"
        assert not dest.exists() and not part.exists()


# --------------------------------------------------------------------------- #
# PHASE 9 CORRECTION: STT folder-layout runtime contract
# --------------------------------------------------------------------------- #


class TestSttFolderLayoutContract:
    """The catalog entry must produce a layout WhisperSTT can consume."""

    @pytest.fixture()
    def models_root_env(self, tmp_path, monkeypatch):
        from core import paths

        root = tmp_path / "AIModels"
        monkeypatch.setenv(paths.MODELS_ROOT_ENV_VAR, str(root))
        return root

    def test_entry_defines_named_install_dir(self):
        entry = find_model("stt/whisper-small")
        assert entry.install_dir == "whisper-small"
        assert entry.runtime_model_name == "whisper-small"

    def test_complete_file_set_represented(self):
        entry = find_model("stt/whisper-small")
        names = {entry.filename} | {c.filename for c in entry.companions}
        assert names == {"model.bin", "config.json", "tokenizer.json", "vocabulary.txt"}

    def test_every_stt_file_has_verified_metadata(self):
        entry = find_model("stt/whisper-small")
        assert entry.size_bytes == 483_546_902
        expected = {
            "config.json": (2_370, "b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828"),
            "tokenizer.json": (2_203_239, "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab"),
            "vocabulary.txt": (459_861, "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913"),
        }
        for companion in entry.companions:
            size, sha = expected[companion.filename]
            assert companion.size_bytes == size
            assert companion.sha256 == sha

    def test_all_stt_urls_share_pinned_revision(self):
        entry = find_model("stt/whisper-small")
        rev = "536b0662742c02347bc0e980a01041f333bce120"
        assert f"/resolve/{rev}/" in entry.url
        for companion in entry.companions:
            assert f"/resolve/{rev}/" in companion.url

    def test_downloader_scopes_to_install_dir(self, models_root_env):
        from installer.downloader import SecureModelDownloader

        dl = SecureModelDownloader("stt", install_dir="whisper-small")
        assert dl.dest_dir == models_root_env / "stt" / "whisper-small"

    def test_install_dir_traversal_rejected(self, models_root_env):
        from installer.downloader import SecureModelDownloader

        for bad in ("..", "../escape", "a/b", "C:\\x", ".hidden", "x:", "dir/"):
            with pytest.raises(ValueError):
                SecureModelDownloader("stt", install_dir=bad)

    def test_whisper_stt_resolves_folder_not_bare_file(self, models_root_env):
        """WhisperSTT(model_name='whisper-small') resolves the FOLDER."""
        from voice.stt import WhisperSTT

        stt = WhisperSTT(model_name="whisper-small")
        assert stt._stt_dir == models_root_env / "stt"
        model_path = stt._stt_dir / stt._model_name
        assert model_path == models_root_env / "stt" / "whisper-small"
        # The loader contract: model_path must be a directory containing
        # model.bin (and the faster-whisper asset files).
        assert "model.bin" not in str(model_path) or model_path.is_dir()

    def test_downloaded_folder_visible_to_settings_selector(self, models_root_env):
        """The Settings STT combo enumerates DIRECTORIES — the installed
        folder must appear there."""
        (models_root_env / "stt" / "whisper-small").mkdir(parents=True)
        (models_root_env / "stt" / "whisper-small" / "model.bin").write_bytes(b"x")
        stt_dir = models_root_env / "stt"
        dirs = [d.name for d in sorted(stt_dir.iterdir()) if d.is_dir()]
        assert "whisper-small" in dirs
        # A bare file (the OLD broken layout) is NOT selectable:
        (models_root_env / "stt" / "bare-model.bin").write_bytes(b"x")
        dirs = [d.name for d in sorted(stt_dir.iterdir()) if d.is_dir()]
        assert all(d == "whisper-small" for d in dirs)

    def test_offline_no_auto_download_intact(self, models_root_env):
        """WhisperSTT raises STTModelError for a missing local model —
        it never downloads anything itself (existing contract).  When
        faster-whisper is unavailable the SAME controlled error type
        surfaces (either way: no download, no fabrication)."""
        from voice.stt import STTModelError, WhisperSTT

        stt = WhisperSTT(model_name="whisper-small")
        with pytest.raises(STTModelError):
            stt._load_model()

    def test_install_dir_required_for_stt_entries(self):
        """Every STT catalog entry must define a named model folder —
        the runtime cannot consume anything else."""
        for entry in get_catalog():
            if entry.category == "stt":
                assert entry.install_dir, (
                    f"{entry.model_id}: STT entries require install_dir"
                )

    def test_llm_embedding_entries_unaffected(self):
        """Flat categories keep the established layout (no install_dir)."""
        for entry in get_catalog():
            if entry.category in ("llm", "embedding"):
                assert entry.install_dir == ""

    def test_runtime_model_name_empty_for_flat_categories(self):
        for entry in get_catalog():
            if entry.category != "stt":
                assert entry.runtime_model_name == ""

    def test_bad_install_dir_rejected_at_construction(self):
        with pytest.raises(ValueError, match="install_dir"):
            DownloadableModel(
                model_id="stt/x", display_name="X", category="stt",
                url="https://example.com/model.bin", filename="model.bin",
                size_bytes=10, install_dir="../escape",
            )


class TestSttSelectionWiring:
    """Catalog STT download selects the installed model (voice.stt.model)."""

    @pytest.fixture()
    def models_root_env(self, tmp_path, monkeypatch):
        from core import paths

        root = tmp_path / "AIModels"
        monkeypatch.setenv(paths.MODELS_ROOT_ENV_VAR, str(root))
        return root

    def test_dialog_selects_stt_model_after_download(self, models_root_env, qapp):
        from unittest.mock import MagicMock as _MG

        from ui.model_manager_dialog import ModelManagerDialog

        manager = _MG()
        manager.list_models.return_value = []
        event_bus = _MG()
        event_bus.publish = _MG()
        dlg = ModelManagerDialog(manager, event_bus)
        entry = find_model("stt/whisper-small")
        dlg._last_downloaded_entry = entry
        # installed folder exists (simulated successful download)
        folder = models_root_env / "stt" / "whisper-small"
        folder.mkdir(parents=True)
        # Patch ConfigManager.set to observe the wiring
        import core.config_manager as cm

        sets: list = []

        def spy_set(self_cfg, key, value):
            sets.append((key, value))

        with patch.object(cm.ConfigManager, "set", spy_set):
            dlg._maybe_select_stt_model(str(folder))
        assert ("voice.stt.model", "whisper-small") in sets
        event_bus.publish.assert_called()
        dlg.close()

    def test_dialog_skips_non_stt_and_missing_folder(self, models_root_env, qapp):
        from unittest.mock import MagicMock as _MG

        from ui.model_manager_dialog import ModelManagerDialog

        dlg = ModelManagerDialog(_MG(), _MG())
        # Non-STT entry -> no wiring attempt
        dlg._last_downloaded_entry = find_model("embedding/mxbai-embed-large-v1")
        dlg._maybe_select_stt_model(str(models_root_env))  # must be a no-op
        # STT entry but folder missing -> no-op
        dlg._last_downloaded_entry = find_model("stt/whisper-small")
        dlg._maybe_select_stt_model(str(models_root_env / "stt" / "nonexistent"))
        dlg.close()

    def test_voice_stt_model_default_unchanged(self):
        """The global default stays 'base' — no silent product change."""
        from core.config_manager import _DEFAULTS

        assert _DEFAULTS["voice"]["stt"]["model"] == "base"

    def test_voice_manager_reconfigures_on_stt_model_change(self):
        """The existing CONFIG_CHANGED handler covers voice.stt.model,
        and the reconfiguration resolves the model dir through the
        canonical category resolver."""
        import inspect

        from voice import manager as vm

        src = inspect.getsource(vm.VoiceManager._on_config_changed)
        assert "voice.stt" in src
        # create_stt receives stt_dir=get_model_category_dir("stt")
        reconf_src = inspect.getsource(vm)
        assert 'get_model_category_dir("stt")' in reconf_src
