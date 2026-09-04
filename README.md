# Offline AI Assistant — Final Application

Standalone, 100% offline AI asistent za Windows sa lokalnom LLM inferencom
(GGUF + llama.cpp, GPU ubrzanje), troslonim memorijom, RAG znanjem,
agentima, voice opcijama i automatizacijom.

## Zahtevi

- **Python 3.11** (verifikovana verzija — `llama-cpp-python` CUDA wheel)
- Windows 10/11
- NVIDIA GPU opciono (testirano na RTX 3080 10GB — full offload)
- AI model u `.gguf` formatu

## Pokretanje

```
pip install -r requirements.txt
python run.py
```

Prvo pokretanje kreira foldere u `%LOCALAPPDATA%\OfflineAI\` i pokreće
instalacioni wizard (7 koraka: Welcome → System Check → AI Model →
Locations → Summary → Installation → Complete).

## AI modeli

Modeli se automatski otkrivaju sa:
- `%LOCALAPPDATA%\OfflineAI\models\llm\` (default)
- foldera projekta `models\llm\`
- Ollama storage (`OLLAMA_MODELS` env varijabla ili `~/.ollama/models`)
- LM Studio keša

Preporučeni model (verifikovan na ovom hardveru): **Qwen2.5-Coder-7B Q4_K_M**
(4.36 GB, tool-calling ✓, staje u 10GB VRAM sa KV cache-om za ctx=4096).

### GPU ubrzanje (opciono)

PyPI `llama-cpp-python` wheel je CPU-only. Za CUDA:
1. Skinuti CUDA wheel sa [llama-cpp-python releases](https://github.com/abetlen/llama-cpp-python/releases) (npr. `v0.3.35-cu124`)
2. `pip install <wheel-fajl> nvidia-cuda-runtime-cu12 nvidia-cublas-cu12`
3. Aplikacija sama detektuje GPU (`auto_gpu_layers=true` → svi slojevi na GPU)

Bez CUDA wheel-a aplikacija radi na CPU (automatski fallback).

## Testiranje

```
pip install -r requirements-dev.txt
pytest tests/            # 92 testa, headless (auto test-mode + offscreen)
python main_original.py --test-runtime   # stvarni GGUF model acceptance test
```

## Struktura

| Folder | Sadržaj |
|---|---|
| `app/` | Bootstrap (ApplicationManager + final AppShell entry) |
| `core/` | Assistant koordinator, EventBus, config, security |
| `ai/` | LLM engine, model discovery/loader/manager, prompts |
| `ui/` | AppShell + stranice + `ui/design/` (tokens/QSS/komponente) |
| `memory/` | 3 sloja: short-term, long-term (SQLite), vektorski |
| `knowledge/` | RAG pipeline, indeksiranje dokumenata |
| `agent/` | LLM planner, ReAct, orkestrator, verifier |
| `tools/` | 16+ alata sa permission slojem |
| `voice/` | STT (faster-whisper), TTS (pyttsx3), wake-word (stub) |
| `automation/` | Workflow engine + scheduler |
| `docs/` | **Dokumentacija projekta** (plan, status, dizajn sistem, modeli) |
| `Izgled Aplikaccije/` | Dizajn preview-i (zvanična tema referenca) |

## Dokumentacija

- `docs/project_plan.md` — plan redizajna
- `docs/current_status.md` — status napretka
- `docs/design_system.md` — Graphite+Emerald specifikacija
- `docs/models_report.md` — analiza i izbor modela
- `docs/environment.md` — dev okruženje
- `docs/qa_checklist.md` — verifikaciona matrica

## Napomene

- Aplikacija je 100% offline — podaci ne izlaze sa računara.
- Glas (STT/TTS), vektorska memorija (faiss) i wake-word su opciona
  proširenja sa stub fallback-om.
- Vision (slike u chatu) nije implementiran — multimodalni modeli se
  koriste samo kao tekstualni LLM.
