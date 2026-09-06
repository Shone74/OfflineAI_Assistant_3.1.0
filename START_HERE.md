# START HERE — Offline AI Assistant

## Running
```
python run.py
```
(double-clicking `run.py` also works)

## First launch
Folders are created in `%LOCALAPPDATA%\OfflineAI\`:
- `config\settings.json`
- `data\assistant.db`
- `logs\`
- `models\llm\`

Then the installation wizard (7 steps) starts. If there is no model, the
application runs in limited (stub) mode — add a model via the Models page.

## Models
Put a `.gguf` file in one of:
```
%LOCALAPPDATA%\OfflineAI\models\llm\       (default)
models\llm\                                 (project folder)
```
Ollama/LM Studio models are discovered automatically.

Recommended: Qwen2.5-Coder-7B Q4_K_M (~4.4 GB).

## GPU (optional)
The application automatically uses the NVIDIA GPU if a CUDA-enabled
llama-cpp-python is available (see README §GPU acceleration).

## Problems?
- Logs: `%LOCALAPPDATA%\OfflineAI\logs\`
- Tests: `pytest tests/` (see `FEATURES.md` for the current verified count)
- Runtime test: `python main_original.py --test-runtime` (requires local GGUF models)
- Documentation: `docs/` folder (plan, status, design, models)
