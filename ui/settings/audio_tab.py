"""Audio settings tab and test worker."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.config_manager import ConfigManager
from core.event_bus import EventBus


class _AudioTestWorker(QThread):
    """Background worker for the Test Microphone feature.

    Records for ``duration`` seconds, then plays back the captured audio
    through the selected output device.  Status is communicated to the GUI
    via Qt signals (queued to the main thread) so widgets are never touched
    from the worker thread.
    """

    status_changed = Signal(str)
    finished = Signal()

    def __init__(self, audio_manager: Any, duration: float = 3.0) -> None:
        super().__init__()
        self._audio = audio_manager
        self._duration = duration

    def run(self) -> None:
        try:
            self.status_changed.emit("Recording...")
            if not self._audio.is_available():
                self.status_changed.emit("Audio test failed: audio backend unavailable")
                self.finished.emit()
                return
            self._audio.start_recording()
            self.msleep(int(self._duration * 1000))
            pcm, sr = self._audio.stop_recording()
            self.status_changed.emit("Playing...")
            if pcm:
                out_dev = self._audio.resolve_output_device()
                if out_dev is not None:
                    self._audio._output_device_index = out_dev
                self._audio.play_audio(pcm, sr)
                self.msleep(int(len(pcm) / (sr * 2) * 1000) + 50)
            self.status_changed.emit("Test complete")
        except OSError as exc:
            self.status_changed.emit(f"Audio test failed: {exc}")
        except RuntimeError as exc:
            self.status_changed.emit(f"Audio test failed: {exc}")
        finally:
            self.finished.emit()


class AudioSettingsTab(QWidget):
    """Tab for audio device selection, WASAPI preferences, and microphone test."""

    _SYSTEM_DEFAULT = "<System Default>"

    def __init__(
        self,
        config: ConfigManager,
        event_bus: EventBus | None = None,
        voice_manager: Any | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._event_bus = event_bus
        self._voice_manager = voice_manager
        self._audio_manager: Any = None
        self._test_worker: Any = None
        self._selected_input_device: dict[str, Any] | None = None
        self._selected_output_device: dict[str, Any] | None = None
        self._input_devices: list[dict[str, Any]] = []
        self._output_devices: list[dict[str, Any]] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)

        # --- Input device ---
        input_group = QGroupBox("Input Device")
        input_layout = QFormLayout(input_group)
        self._input_combo = QComboBox()
        self._input_combo.currentIndexChanged.connect(self._on_input_device_changed)
        input_layout.addRow(QLabel("Microphone"), self._input_combo)
        main_layout.addWidget(input_group)

        # --- Output device ---
        output_group = QGroupBox("Output Device")
        output_layout = QFormLayout(output_group)
        self._output_combo = QComboBox()
        self._output_combo.currentIndexChanged.connect(self._on_output_device_changed)
        output_layout.addRow(QLabel("Output Device"), self._output_combo)
        main_layout.addWidget(output_group)

        # --- WASAPI preferences ---
        wasapi_group = QGroupBox("WASAPI Capture")
        wasapi_layout = QVBoxLayout(wasapi_group)
        self._prefer_wasapi_chk = QCheckBox("Prefer WASAPI")
        self._prefer_wasapi_chk.setChecked(True)
        self._prefer_wasapi_chk.stateChanged.connect(
            lambda state: self._on_wasapi_preference_changed(bool(state))
        )
        wasapi_layout.addWidget(self._prefer_wasapi_chk)

        self._fallback_chk = QCheckBox("Allow WASAPI fallback to MME")
        self._fallback_chk.setChecked(True)
        self._fallback_chk.stateChanged.connect(
            lambda state: self._on_fallback_changed(bool(state))
        )
        wasapi_layout.addWidget(self._fallback_chk)
        main_layout.addWidget(wasapi_group)

        # --- Test Microphone ---
        test_group = QGroupBox("Microphone Test")
        test_layout = QVBoxLayout(test_group)
        btn_row = QHBoxLayout()
        self._btn_test = QPushButton("Test Microphone")
        self._btn_test.clicked.connect(self._on_test_microphone)
        btn_row.addWidget(self._btn_test)
        self._btn_refresh = QPushButton("Refresh Devices")
        self._btn_refresh.clicked.connect(self._on_refresh_devices)
        btn_row.addWidget(self._btn_refresh)
        test_layout.addLayout(btn_row)
        self._test_status = QLabel("Ready")
        self._test_status.setStyleSheet("color: #8C9692;")
        test_layout.addWidget(self._test_status)
        main_layout.addWidget(test_group)

        # --- Device information ---
        info_group = QGroupBox("Selected Device Information")
        info_layout = QFormLayout(info_group)
        self._info_name = QLabel("—")
        self._info_hostapi = QLabel("—")
        self._info_samplerate = QLabel("—")
        self._info_channels = QLabel("—")
        self._info_index = QLabel("—")
        info_layout.addRow(QLabel("Device name"), self._info_name)
        info_layout.addRow(QLabel("Host API"), self._info_hostapi)
        info_layout.addRow(QLabel("Native sample rate"), self._info_samplerate)
        info_layout.addRow(QLabel("Channels"), self._info_channels)
        info_layout.addRow(QLabel("Runtime index"), self._info_index)
        main_layout.addWidget(info_group)

        main_layout.addStretch()

    def load_settings(self, config: ConfigManager) -> None:
        self._populate_devices()
        input_name = config.get("audio.input_device_name", "")
        input_hostapi = config.get("audio.input_device_hostapi", "")
        self._select_combo_device(self._input_combo, input_name, input_hostapi)

        output_name = config.get("audio.output_device_name", "")
        output_hostapi = config.get("audio.output_device_hostapi", "")
        self._select_combo_device(self._output_combo, output_name, output_hostapi)

        self._prefer_wasapi_chk.setChecked(config.get("audio.prefer_wasapi", True))
        self._fallback_chk.setChecked(config.get("audio.wasapi_fallback_to_mme", True))

    def save_settings(self, config: ConfigManager) -> None:
        selected = self._combo_device_data(self._input_combo)
        if selected is None:
            config.set("audio.input_device_index", None)
            config.set("audio.input_device_name", "")
            config.set("audio.input_device_hostapi", "")
        else:
            config.set("audio.input_device_index", selected.get("index"))
            config.set("audio.input_device_name", selected.get("name", ""))
            config.set("audio.input_device_hostapi", selected.get("hostapi_name", ""))

        selected_out = self._combo_device_data(self._output_combo)
        if selected_out is None:
            config.set("audio.output_device_index", None)
            config.set("audio.output_device_name", "")
            config.set("audio.output_device_hostapi", "")
        else:
            config.set("audio.output_device_index", selected_out.get("index"))
            config.set("audio.output_device_name", selected_out.get("name", ""))
            config.set("audio.output_device_hostapi", selected_out.get("hostapi_name", ""))

        config.set("audio.prefer_wasapi", self._prefer_wasapi_chk.isChecked())
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "audio.prefer_wasapi", "value": self._prefer_wasapi_chk.isChecked()}
            )
        config.set("audio.wasapi_fallback_to_mme", self._fallback_chk.isChecked())
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "audio.wasapi_fallback_to_mme", "value": self._fallback_chk.isChecked()}
            )
        # Notify VoiceManager to rebuild audio managers with updated device config
        input_name = config.get("audio.input_device_name", "")
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "audio.input", "value": input_name}
            )
        output_name = config.get("audio.output_device_name", "")
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "audio.output", "value": output_name}
            )

    def _get_audio_manager(self) -> Any:
        """Return the SoundDeviceAudioManager from VoiceManager, or None."""
        if self._audio_manager is not None:
            return self._audio_manager
        if self._voice_manager is not None:
            am = getattr(self._voice_manager, "_audio", None)
            if am is not None and am.is_available():
                self._audio_manager = am
        return self._audio_manager

    def _populate_devices(self) -> None:
        am = self._get_audio_manager()
        if am is None or not am.is_available():
            self._input_combo.blockSignals(True)
            self._input_combo.clear()
            self._input_combo.addItem(self._SYSTEM_DEFAULT)
            self._input_combo.setItemData(0, {"system_default": True})
            self._input_combo.setCurrentIndex(0)
            self._input_combo.blockSignals(False)

            self._output_combo.blockSignals(True)
            self._output_combo.clear()
            self._output_combo.addItem(self._SYSTEM_DEFAULT)
            self._output_combo.setItemData(0, {"system_default": True})
            self._output_combo.setCurrentIndex(0)
            self._output_combo.blockSignals(False)
            return
        if not hasattr(am, "list_devices") or not callable(am.list_devices):
            return

        # --- Input devices ---
        saved_input_name = self._config.get("audio.input_device_name", "")
        saved_input_hostapi = self._config.get("audio.input_device_hostapi", "")
        self._input_devices = am.list_devices()
        self._input_combo.blockSignals(True)
        self._build_device_combo(self._input_combo, self._input_devices, "input")
        self._restore_combo_selection(
            self._input_combo, self._input_devices, "input",
            saved_input_name, saved_input_hostapi,
        )
        self._input_combo.blockSignals(False)

        # --- Output devices ---
        saved_output_name = self._config.get("audio.output_device_name", "")
        saved_output_hostapi = self._config.get("audio.output_device_hostapi", "")
        self._output_devices = (
            am.list_output_devices()
            if hasattr(am, "list_output_devices") and callable(am.list_output_devices)
            else []
        )
        self._output_combo.blockSignals(True)
        self._build_device_combo(self._output_combo, self._output_devices, "output")
        self._restore_combo_selection(
            self._output_combo, self._output_devices, "output",
            saved_output_name, saved_output_hostapi,
        )
        self._output_combo.blockSignals(False)

        # Update device info for the restored selection
        self._update_device_info(
            self._combo_device_data(self._input_combo), "input"
        )
        self._update_device_info(
            self._combo_device_data(self._output_combo), "output"
        )

    def _host_api_name(self, devices: list[dict[str, Any]], device: dict[str, Any]) -> str:
        """Resolve the human-readable host API name for a device."""
        import sounddevice as sd

        ha_idx = device.get("hostapi", -1)
        if ha_idx >= 0:
            try:
                apis = sd.query_hostapis()
                return apis[ha_idx]["name"]
            except Exception:
                logger.debug("host API name lookup failed", exc_info=True)
        return "Unknown"

    def _format_device_label(
        self, device: dict[str, Any], hostapi_name: str, kind: str
    ) -> str:
        name = device.get("name", "Unknown")
        sr = device.get("default_samplerate", 0)
        if kind == "input":
            ch = device.get("max_input_channels", 0)
        else:
            ch = device.get("max_output_channels", 0)
        sr_str = f"{int(sr)} Hz" if sr else "?"
        return f"{name} — {hostapi_name} — {sr_str} — {ch} ch"

    def _build_device_combo(
        self, combo: QComboBox, devices: list[dict[str, Any]], kind: str
    ) -> None:
        """Populate *combo* with System Default + device items.

        Signals remain blocked — the caller (``_populate_devices``) is
        responsible for unblocking after restoring the persisted selection,
        so that ``_on_input_device_changed`` does not fire during initialization.
        """
        combo.clear()
        combo.addItem(self._SYSTEM_DEFAULT)
        combo.setItemData(0, {"system_default": True})
        for dev in devices:
            ha_name = self._host_api_name(devices, dev)
            label = self._format_device_label(dev, ha_name, kind)
            data = {
                "system_default": False,
                "index": dev.get("index"),
                "name": dev.get("name", ""),
                "hostapi_name": ha_name,
                "hostapi_index": dev.get("hostapi", -1),
                "sample_rate": dev.get("default_samplerate", 0),
                "channels": dev.get("max_input_channels" if kind == "input" else "max_output_channels", 0),
            }
            combo.addItem(label)
            combo.setItemData(combo.count() - 1, data)

    def _restore_combo_selection(
        self,
        combo: QComboBox,
        devices: list[dict[str, Any]],
        kind: str,
        saved_name: str,
        saved_hostapi: str,
    ) -> None:
        if not saved_name:
            combo.setCurrentIndex(0)
            return
        found = False
        for i in range(combo.count()):
            data = combo.itemData(i)
            if (
                data
                and not data.get("system_default")
                and saved_name in data.get("name", "")
                and (
                    not saved_hostapi
                    or saved_hostapi in data.get("hostapi_name", "")
                )
            ):
                combo.setCurrentIndex(i)
                found = True
                break
        if not found:
            combo.setCurrentIndex(0)
            # Mark unavailable
            self._set_device_unavailable(combo)

    def _select_combo_device(
        self, combo: QComboBox, name: str, hostapi: str
    ) -> None:
        if not name:
            combo.setCurrentIndex(0)
            return
        for i in range(combo.count()):
            data = combo.itemData(i)
            if (
                data
                and not data.get("system_default")
                and name in data.get("name", "")
                and (
                    not hostapi
                    or hostapi in data.get("hostapi_name", "")
                )
            ):
                    combo.setCurrentIndex(i)
                    return
        combo.setCurrentIndex(0)

    def _combo_device_data(self, combo: QComboBox) -> dict[str, Any] | None:
        data = combo.itemData(combo.currentIndex())
        if data and data.get("system_default"):
            return None
        return data if data else None

    def _set_device_unavailable(self, combo: QComboBox) -> None:
        label = combo.itemText(combo.currentIndex())
        if self._SYSTEM_DEFAULT not in label:
            combo.setItemText(combo.currentIndex(), f"⚠ {label} (unavailable)")

    def _on_input_device_changed(self, index: int) -> None:
        data = self._combo_device_data(self._input_combo)
        if data is None:
            self._update_device_info(None, "input")
            self._clear_audio_config(self._config)
            return
        self._update_device_info(data, "input")
        self._persist_input_device(data)

    def _on_output_device_changed(self, index: int) -> None:
        data = self._combo_device_data(self._output_combo)
        if data is None:
            self._update_device_info(None, "output")
            self._clear_audio_output_config(self._config)
            return
        self._update_device_info(data, "output")
        self._persist_output_device(data)

    def _persist_input_device(self, data: dict[str, Any]) -> None:
        self._config.set("audio.input_device_index", data.get("index"))
        self._config.set("audio.input_device_name", data.get("name", ""))
        self._config.set("audio.input_device_hostapi", data.get("hostapi_name", ""))
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED",
                {"key": "audio.input", "value": data.get("name", "")},
            )

    def _clear_audio_config(self, config: ConfigManager) -> None:
        config.set("audio.input_device_index", None)
        config.set("audio.input_device_name", "")
        config.set("audio.input_device_hostapi", "")
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED",
                {"key": "audio.input", "value": ""},
            )

    def _persist_output_device(self, data: dict[str, Any]) -> None:
        self._config.set("audio.output_device_index", data.get("index"))
        self._config.set("audio.output_device_name", data.get("name", ""))
        self._config.set("audio.output_device_hostapi", data.get("hostapi_name", ""))
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED",
                {"key": "audio.output", "value": data.get("name", "")},
            )

    def _clear_audio_output_config(self, config: ConfigManager) -> None:
        config.set("audio.output_device_index", None)
        config.set("audio.output_device_name", "")
        config.set("audio.output_device_hostapi", "")
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED",
                {"key": "audio.output", "value": ""},
            )

    def _on_wasapi_preference_changed(self, checked: bool) -> None:
        self._config.set("audio.prefer_wasapi", checked)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "audio.prefer_wasapi", "value": checked}
            )

    def _on_fallback_changed(self, checked: bool) -> None:
        self._config.set("audio.wasapi_fallback_to_mme", checked)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "audio.wasapi_fallback_to_mme", "value": checked}
            )

    def _on_refresh_devices(self) -> None:
        self._populate_devices()

    def _on_test_microphone(self) -> None:
        am = self._get_audio_manager()
        if am is None or not am.is_available():
            self._test_status.setText("Audio test failed: audio backend unavailable")
            return
        self._btn_test.setEnabled(False)
        self._btn_refresh.setEnabled(False)
        self._test_worker = _AudioTestWorker(am)
        self._test_worker.status_changed.connect(self._on_test_status_changed)
        self._test_worker.finished.connect(self._on_test_finished)
        self._test_worker.start()

    def _on_test_status_changed(self, status: str) -> None:
        self._test_status.setText(status)

    def _on_test_finished(self) -> None:
        self._btn_test.setEnabled(True)
        self._btn_refresh.setEnabled(True)
        self._test_worker = None

    def _update_device_info(self, data: dict[str, Any] | None, kind: str) -> None:
        if data is None:
            self._info_name.setText("—")
            self._info_hostapi.setText("—")
            self._info_samplerate.setText("—")
            self._info_channels.setText("—")
            self._info_index.setText("—")
            return
        self._info_name.setText(data.get("name", "—"))
        self._info_hostapi.setText(data.get("hostapi_name", "—"))
        sr = data.get("sample_rate", 0)
        self._info_samplerate.setText(f"{int(sr)} Hz" if sr else "—")
        ch = data.get("channels", 0)
        self._info_channels.setText(str(ch) if ch else "—")
        self._info_index.setText(str(data.get("index", "—")))