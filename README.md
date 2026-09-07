# Offline AI Assistant — Final Application

Standalone, 100% offline AI assistant for Windows with local LLM inference
(GGUF + llama.cpp, GPU acceleration), three-tier memory, RAG knowledge,
agents, voice options, and automation.

## Requirements

- **Python 3.11** (verified version — `llama-cpp-python` CUDA wheel)
- Windows 10/11
- NVIDIA GPU optional (tested on RTX 3080 10GB — full offload)
- AI model in `.gguf` format

## Running

```
pip install -r requirements.txt
python run.py
```

First launch creates the folders in `%LOCALAPPDATA%\OfflineAI\` and starts
the installation wizard (7 steps: Welcome → System Check → AI Model →
Locations → Summary → Installation → Complete).

## AI models

Models are automatically discovered from:
- `%LOCALAPPDATA%\OfflineAI\models\llm\` (default)
- the project folder `models\llm\`
- Ollama storage (`OLLAMA_MODELS` env variable or `~/.ollama/models`)
- the LM Studio cache

Recommended model (verified on this hardware): **Qwen2.5-Coder-7B Q4_K_M**
(4.36 GB, tool-calling ✓, fits in 10GB VRAM with KV cache for ctx=4096).

### GPU acceleration (optional)

The PyPI `llama-cpp-python` wheel is CPU-only. For CUDA:
1. Download the CUDA wheel from [llama-cpp-python releases](https://github.com/abetlen/llama-cpp-python/releases) (e.g. `v0.3.35-cu124`)
2. `pip install <wheel-file> nvidia-cuda-runtime-cu12 nvidia-cublas-cu12`
3. The application detects the GPU automatically (`auto_gpu_layers=true` → all layers on GPU)

Without the CUDA wheel, the application runs on CPU (automatic fallback).

## Testing

```
pip install -r requirements-dev.txt
pytest tests/            # full suite, headless (auto test-mode + offscreen)
```

The current suite size and verification matrix live in `FEATURES.md`
(single source of truth — avoid hardcoding counts in multiple documents).
A real-GGUF runtime acceptance test is available via the legacy entry
point: `python main_original.py --test-runtime` (requires local model
files).

## Structure

| Folder | Contents |
|---|---|
| `app/` | Bootstrap (ApplicationManager + final AppShell entry) |
| `core/` | Assistant coordinator, EventBus, config, security |
| `ai/` | LLM engine, model discovery/loader/manager, prompts |
| `ui/` | AppShell + pages + `ui/design/` (tokens/QSS/components) |
| `memory/` | 3 tiers: short-term, long-term (SQLite), vector |
| `knowledge/` | RAG pipeline, document indexing |
| `agent/` | LLM planner, ReAct, orchestrator, verifier |
| `tools/` | 16+ tools with a permission layer |
| `voice/` | STT (faster-whisper), TTS (pyttsx3), wake-word (openwakeword, optional) |
| `automation/` | Workflow engine + scheduler (worker-thread execution) |
| `docs/` | **Project documentation** (plan, status, design system, models) |
| `design_previews/` | Design previews (official theme reference) |

## Documentation

- `FEATURES.md` — verified feature matrix + test counts (source of truth)
- `docs/project_plan.md` — redesign plan
- `docs/current_status.md` — progress status
- `docs/design_system.md` — Graphite+Emerald specification
- `docs/models_report.md` — model analysis and selection
- `docs/environment.md` — dev environment
- `docs/qa_checklist.md` — verification matrix

## Notes

- The application is 100% offline — data never leaves the computer.
- Voice (STT/TTS), vector memory (faiss), and wake-word (openwakeword) are
  optional extensions with stub fallback.
- Vision (images in chat) works with vision-capable GGUF models when their
  `mmproj` projector file is placed next to the model; without a projector
  the model runs text-only and image messages are politely refused.
- Automation tasks and "Run Now" execute on background workers — the GUI
  thread never blocks on tool/LLM work.
