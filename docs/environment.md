# Environment — Development Environment and Hardware

**Date:** 2026-09-04

---

## 1. Hardware (verified)

| Component | Value |
|---|---|
| CPU | AMD Ryzen 7 5700X — 8 cores / 16 threads |
| RAM | 32 GB |
| GPU | NVIDIA GeForce RTX 3080 — **10 GB VRAM** (driver 616.56) |
| OS | Windows 11 Pro 64-bit |
| Drives | NVMe (system) + HDD E: (3.27 TB free) + G: project (238 GB free) |

## 2. Python environments on the system

| Version | Path | Status for the project |
|---|---|---|
| **3.11.9** | `C:\Users\Bota\AppData\Local\Programs\Python\Python311\python.exe` | ✅ **VERIFIED — use for development and tests** |
| 3.14.7 | `E:\Python\python.exe` (py default `*`) | ⛔ `llama-cpp-python` NOT installed/unavailable — do NOT use |

### Why 3.11:
- 3.11 has: `llama_cpp_python 0.3.35`, `PySide6 6.11.1`, `pytest 9.1.1`, `pytest-asyncio`, `faster-whisper 1.2.1`, `pyttsx3`, `sounddevice`, `requests`, `pywin32`, `psutil`, `ollama`
- 3.11 lacks (add in step 0.2): `scipy`, `nvidia-ml-py3`
- `__pycache__` in the project confirms the app has already been run under 3.11 (and 3.14)
- pyproject requires `>=3.13` — **incorrect**; fix in step 1.5 to `>=3.11`

## 3. Standard commands

```powershell
# Active interpreter (alias for everything below):
$py = "C:\Users\Bota\AppData\Local\Programs\Python\Python311\python.exe"

# Test suite (headless):
$env:QT_QPA_PLATFORM="offscreen"; $env:OFFLINE_AI_TEST_MODE="1"
& $py -m pytest tests/ -v

# Running the application (GUI):
& $py run.py

# Model runtime acceptance test:
& $py main_original.py --test-runtime

# Lint / typecheck:
& $py -m ruff check .
& $py -m mypy .  # (if installed; add to requirements-dev)
```

## 4. Data paths (runtime)

| What | Path |
|---|---|
| Config | `%LOCALAPPDATA%\OfflineAI\config\settings.json` (exists, analyzed) |
| Database | `%LOCALAPPDATA%\OfflineAI\data\assistant.db` |
| Logs | `%LOCALAPPDATA%\OfflineAI\logs\` |
| Models (AppData default) | `%LOCALAPPDATA%\OfflineAI\models\llm\` |
| **Models (project)** | `G:\Projekti\Finalna Aplikacija\models\llm\` (Qwen2.5-Coder-7B + Phi-4-mini copied) |
| Model candidates | `E:\models` (do not touch; source) |

## 5. Test mode flags

| Env var | Effect |
|---|---|
| `OFFLINE_AI_TEST_MODE=1` | StubEngine/StubModelLoader fallback everywhere (ModelManager, engine, assistant); UNKNOWN models are treated as LLM |
| `QT_QPA_PLATFORM=offscreen` | Headless Qt for CI/pytest |
| `OLLAMA_MODELS` / `OLLAMA_MODELS_DIR` | Override for the Ollama storage location |

Note: `tests/test_final_app.py` does NOT set these flags itself — for now set them in the command (plan: conftest.py in step 0.3).
