# Models Report — Analysis and Decision on AI Models

**Date:** 2026-09-04
**Candidate source:** `E:\models`
**Goal:** Selection of the most suitable models for the application (hardware: Ryzen 7 5700X 8C/16T, 32GB RAM, **RTX 3080 10GB VRAM**, Windows 11)

---

## 1. List of candidates (E:\models) and classification

Classification performed by the project's actual parser (`ai/models/model_loader.py` — `_read_gguf_metadata` + `classify_model` + `infer_capabilities`):

| Candidate | Size | Arch | Type | Assessment |
|---|---|---|---|---|
| Ollama blob `sha256-60e05f...` (= **qwen2.5-coder:7b**, manifest confirmed) | 4.36 GB | qwen2 | LLM | ✅ **SELECTED — primary** |
| `microsoft_Phi-4-mini-instruct-Q6_K_L.gguf` | 3.08 GB | phi3 | LLM | ✅ **SELECTED — secondary** |
| Ollama blob `sha256-119419...` (= qwen3-coder:30b) | 17.3 GB | qwen35 (unknown to the parser) | UNKNOWN | ⛔ Too large for 10GB VRAM; architecture unknown to the parser |
| `Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf` | 4.36 GB | qwen2vl | VISION_LLM | ⛔ Multimodal inference is NOT implemented in the chat pipeline — images would not work |
| `mmproj-Qwen2.5-VL-7B...gguf` / `mmproj-Bonsai...` | 0.85 GB | clip | PROJECTOR | ⛔ Projectors are not used in the pipeline |
| `gemma4-coding-Q2_K.gguf` | 4.50 GB | gemma4 | LLM | ⛔ Arch `gemma4` unknown to the parser; Q2_K too degraded; no tool-calling flags |
| `Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q8_0.gguf` | 4.17 GB | qwen35 | UNKNOWN | ⛔ Arch `qwen35` not supported in the loader; "Uncensored-Aggressive" is a careless choice for an assistant |
| `Bonsai-27B-Q1_0.gguf` | 3.54 GB | qwen35 | UNKNOWN | ⛔ 27B at Q1_0 — extreme degradation; architecture unknown |
| `flux-2-klein-4b-Q4_K_M.gguf` | 2.43 GB | flux | DIFFUSION | ⛔ Diffusion model — rejected by the chat engine |

---

## 2. Decision: selected models

### Primary: Qwen2.5-Coder-7B — Q4_K_M (4.36 GB)
- **Why:** The `qwen2` architecture is first-class supported (chat-compatible, tool_calling ✓, function_calling ✓, structured/JSON output ✓ — crucial for the agent system). The 4.36 GB size fits comfortably in 10GB VRAM with room for the KV cache → **full GPU offload** (auto_gpu_layers=True → all layers on the RTX 3080).
- Q4_K_M is the best quality/size balance for the 7B class.
- Despite the "Coder" name, the model is a good general chat model (Qwen2.5-Coder is based on its base Qwen2.5 training).
- **Source:** Ollama blob `sha256-60e05f2100071479f596b964f89f510f057ce397ea22f2833a0cfe029bfc2463` (manifest `registry.ollama.ai/library/qwen2.5-coder/7b` confirms the model layer).

### Secondary: Phi-4-mini-instruct — Q6_K_L (3.08 GB)
- **Why:** Higher-quality quant (Q6_K_L), low VRAM consumption (3 GB → leaves plenty of room for context), fast responses, arch `phi3` known to the parser, tool_calling ✓.
- Purpose: fast responses / low-VRAM scenario / fallback.

### Not used
- All other candidates (reasons in the table above). The Vision model is specifically rejected because multimodal inference is not implemented (the chat widget does not accept images, mmproj is not attached).

---

## 3. Layout and paths

### Copied into the project (this step is DONE):
```
G:\Projekti\Finalna Aplikacija\models\llm\Qwen2.5-Coder-7B-Q4_K_M.gguf      (4.36 GB)
G:\Projekti\Finalna Aplikacija\models\llm\microsoft_Phi-4-mini-instruct-Q6_K_L.gguf  (3.08 GB)
```
This makes the project **self-contained** — it works without the E:\ drive. The origin blobs are kept in E:\models.

### How the application finds models:
- `ai.models_dir` (default `%LOCALAPPDATA%\OfflineAI\models\llm`) + the `ai.model_search_paths` list are scanned recursively for `*.gguf`
- Current `settings.json`: `models_dir: "E:/models"` + search_paths `[AppData]` — E:/models is scanned and the Ollama blobs are visible from it (magic-byte check works for extension-less files)
- **Recommendation for phase 6.1:** add `G:\Projekti\Finalna Aplikacija\models\llm` to `model_search_paths` (or use it as `models_dir` in dev mode), so the selected models are discovered without depending on the E: drive

### GPU offload:
- `auto_gpu_layers: True` → `n_gpu_layers=999` → all layers on GPU (llama.cpp caps it internally)
- Qwen2.5-Coder-7B Q4_K_M (4.36 GB) + KV cache for n_ctx=4096 ≈ 5.5–6 GB → comfortably within 10GB VRAM
- CUDA DLLs: the `llama_cpp` pip wheel ships `ggml-cuda.dll`; the helper adds the pip nvidia/cuXX/bin folders to PATH

---

## 4. Recommendations for inference parameters (phase 6.3)

| Parameter | Current | Recommendation | Reason |
|---|---|---|---|
| `n_ctx` | 512 | **4096** | 512 truncates the conversation; Qwen2.5 supports up to 32k; 4k is the VRAM/range balance |
| `max_tokens` | 204 | **1024** | 204 is an OK minimum, but 1024 for full explanatory answers |
| `n_threads` | 4 | **8** | There are 8 physical cores; GPU offload does the heavy lifting anyway |
| `temperature` | 0.7 | 0.7 | Standard for chat |
| `model_name` | "qwen-7b" | clear it → default discovery | "qwen-7b" does not map to any file |

---

## 5. Embedding models (memory/RAG)

- Currently `memory.embedding_model: "stub"` — vector memory uses a pure-Python kNN fallback (works, slower).
- In `E:\models` **there is no valid embedding model** (mmproj files are PROJECTOR, not EMBEDDING; flux is DIFFUSION).
- **Decision (step 6.4):** keep the stub for now; optionally add a small BGE/E5 GGUF embedding model later when knowledge scaling is needed. Unchanged for this redesign.

---

## 6. Verification plan for models (phase 6.1/6.2)

```powershell
# 1. Load + headless generation (without GUI):
& "C:\Users\Bota\AppData\Local\Programs\Python\Python311\python.exe" main_original.py --test-runtime

# 2. GPU check during generation (in another terminal):
nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv -l 1

# 3. Model discovery (quick check):
& "C:\Users\Bota\AppData\Local\Programs\Python\Python311\python.exe" -c "import sys; sys.path.insert(0, r'G:\Projekti\Finalna Aplikacija'); from ai.models.discovery import discover_all_models; print(discover_all_models())"
```
