# Environment — Razvojno okruženje i hardver

**Datum:** 2026-09-04

---

## 1. Hardver (verifikovano)

| Komponenta | Vrednost |
|---|---|
| CPU | AMD Ryzen 7 5700X — 8 jezgara / 16 threadova |
| RAM | 32 GB |
| GPU | NVIDIA GeForce RTX 3080 — **10 GB VRAM** (driver 616.56) |
| OS | Windows 11 Pro 64-bit |
| Diskovi | NVMe (sistem) + HDD E: (3.27 TB slobodno) + G: projekat (238 GB slobodno) |

## 2. Python okruženja na sistemu

| Verzija | Putanja | Status za projekat |
|---|---|---|
| **3.11.9** | `C:\Users\Bota\AppData\Local\Programs\Python\Python311\python.exe` | ✅ **VERIFIED — koristiti za razvoj i testove** |
| 3.14.7 | `E:\Python\python.exe` (py default `*`) | ⛔ `llama-cpp-python` NIJE instaliran/nedostupan — NE koristiti |

### Zašto 3.11:
- 3.11 ima: `llama_cpp_python 0.3.35`, `PySide6 6.11.1`, `pytest 9.1.1`, `pytest-asyncio`, `faster-whisper 1.2.1`, `pyttsx3`, `sounddevice`, `requests`, `pywin32`, `psutil`, `ollama`
- 3.11 nema (dodati u koraku 0.2): `scipy`, `nvidia-ml-py3`
- `__pycache__` u projektu potvrđuje da je app već pokretana pod 3.11 (i 3.14)
- pyproject traži `>=3.13` — **neispravno**; ispravka u koraku 1.5 na `>=3.11`

## 3. Standardne komande

```powershell
# Aktivni interpreter (alias za sve dalje):
$py = "C:\Users\Bota\AppData\Local\Programs\Python\Python311\python.exe"

# Test suite (headless):
$env:QT_QPA_PLATFORM="offscreen"; $env:OFFLINE_AI_TEST_MODE="1"
& $py -m pytest tests/ -v

# Pokretanje aplikacije (GUI):
& $py run.py

# Model runtime acceptance test:
& $py main_original.py --test-runtime

# Lint / typecheck:
& $py -m ruff check .
& $py -m mypy .  # ( ako su instalirani; dodati u requirements-dev )
```

## 4. Putanje podataka (runtime)

| Šta | Putanja |
|---|---|
| Config | `%LOCALAPPDATA%\OfflineAI\config\settings.json` (postoji, analiziran) |
| Baza | `%LOCALAPPDATA%\OfflineAI\data\assistant.db` |
| Logovi | `%LOCALAPPDATA%\OfflineAI\logs\` |
| Modeli (AppData default) | `%LOCALAPPDATA%\OfflineAI\models\llm\` |
| **Modeli (projekat)** | `G:\Projekti\Finalna Aplikacija\models\llm\` (Qwen2.5-Coder-7B + Phi-4-mini kopirani) |
| Kandidati modela | `E:\models` (ne dirati; izvor) |

## 5. Test mode flagovi

| Env var | Efekat |
|---|---|
| `OFFLINE_AI_TEST_MODE=1` | StubEngine/StubModelLoader fallback svuda (ModelManager, engine, assistant); UNKNOWN modeli se tretiraju kao LLM |
| `QT_QPA_PLATFORM=offscreen` | Headless Qt za CI/pytest |
| `OLLAMA_MODELS` / `OLLAMA_MODELS_DIR` | Override za Ollama storage lokaciju |

Napomena: `tests/test_final_app.py` NE postavlja ove flagove sam — za sada ih setovati u komandi (plan: conftest.py u koraku 0.3).
