# Models Report — Analiza i odluka o AI modelima

**Datum:** 2026-09-04
**Izvor kandidata:** `E:\models`
**Cilj:** Izbor najpogodnijih modela za aplikaciju (hardver: Ryzen 7 5700X 8C/16T, 32GB RAM, **RTX 3080 10GB VRAM**, Windows 11)

---

## 1. Spisak kandidata (E:\models) i klasifikacija

Klasifikacija izvršena stvarnim parserom projekta (`ai/models/model_loader.py` — `_read_gguf_metadata` + `classify_model` + `infer_capabilities`):

| Kandidat | Veličina | Arch | Tip | Procena |
|---|---|---|---|---|
| Ollama blob `sha256-60e05f...` (= **qwen2.5-coder:7b**, manifest potvrđen) | 4.36 GB | qwen2 | LLM | ✅ **IZABRAN — primarni** |
| `microsoft_Phi-4-mini-instruct-Q6_K_L.gguf` | 3.08 GB | phi3 | LLM | ✅ **IZABRAN — sekundarni** |
| Ollama blob `sha256-119419...` (= qwen3-coder:30b) | 17.3 GB | qwen35 (nepoznat parseru) | UNKNOWN | ⛔ Prevelik za 10GB VRAM; arhitektura nije poznata parseru |
| `Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf` | 4.36 GB | qwen2vl | VISION_LLM | ⛔ Multimodalna inferencija NIJE implementirana u chat pipeline-u — slike ne bi radile |
| `mmproj-Qwen2.5-VL-7B...gguf` / `mmproj-Bonsai...` | 0.85 GB | clip | PROJECTOR | ⛔ Projektori se ne koriste u pipeline-u |
| `gemma4-coding-Q2_K.gguf` | 4.50 GB | gemma4 | LLM | ⛔ Arch `gemma4` nije poznata parseru; Q2_K previše degradirana; bez tool-calling flagova |
| `Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q8_0.gguf` | 4.17 GB | qwen35 | UNKNOWN | ⛔ Arch `qwen35` nije podržana u loader-u; "Uncensored-Aggressive" nepromišljen izbor za asistenta |
| `Bonsai-27B-Q1_0.gguf` | 3.54 GB | qwen35 | UNKNOWN | ⛔ 27B na Q1_0 — ekstremna degradacija; arhitektura nepoznata |
| `flux-2-klein-4b-Q4_K_M.gguf` | 2.43 GB | flux | DIFFUSION | ⛔ Diffusion model — chat engine ga odbija |

---

## 2. Odluka: izabrani modeli

### Primarni: Qwen2.5-Coder-7B — Q4_K_M (4.36 GB)
- **Zašto:** Arhitektura `qwen2` je prvorazredno podržana (chat-compatible, tool_calling ✓, function_calling ✓, structured/JSON output ✓ — ključno za agent sistem). Veličina 4.36 GB staje komotno u 10GB VRAM sa prostorom za KV cache → **potpuni GPU offload** (auto_gpu_layers=True → svi slojevi na RTX 3080).
- Q4_K_M je najbolji balans kvalitet/veličina za 7B klasu.
- Despite "Coder" imenu, model je dobar generalni chat model (Qwen2.5-Coder je na svom baznom Qwen2.5 treningu).
- **Izvor:** Ollama blob `sha256-60e05f2100071479f596b964f89f510f057ce397ea22f2833a0cfe029bfc2463` (manifest `registry.ollama.ai/library/qwen2.5-coder/7b` potvrđuje model layer).

### Sekundarni: Phi-4-mini-instruct — Q6_K_L (3.08 GB)
- **Zašto:** Kvalitetniji kvant (Q6_K_L), mala potrošnja VRAM (3 GB → ostavlja mnogo mesta za kontekst), brz odgovor, arch `phi3` poznata parseru, tool_calling ✓.
- Namena: brzi odgovori / low-VRAM scenario / fallback.

### Ne koriste se
- Svi ostali kandidati (razlozi u tabeli iznad). Vision model se posebno odbija jer multimodalna inferencija nije implementirana (chat widget ne prima slike, mmproj se ne spaja).

---

## 3. Raspored i putanje

### Kopirano u projekat (ovaj korak je IZVRŠEN):
```
G:\Projekti\Finalna Aplikacija\models\llm\Qwen2.5-Coder-7B-Q4_K_M.gguf      (4.36 GB)
G:\Projekti\Finalna Aplikacija\models\llm\microsoft_Phi-4-mini-instruct-Q6_K_L.gguf  (3.08 GB)
```
Ovo čini projekat **samostalnim** — radi i bez E:\ diska. Origin blob zadržan u E:\models.

### Kako aplikacija pronalazi modele:
- `ai.models_dir` (default `%LOCALAPPDATA%\OfflineAI\models\llm`) + `ai.model_search_paths` lista se skeniraju rekurzivno za `*.gguf`
- Trenutni `settings.json`: `models_dir: "E:/models"` + search_paths `[AppData]` — E:/models se skenira i iz njega se vide i Ollama blob-ovi (magic-byte provera radi za bezekstenzione fajlove)
- **Preporaka za fazu 6.1:** dodati `G:\Projekti\Finalna Aplikacija\models\llm` u `model_search_paths` (ili koristiti kao `models_dir` u dev režimu), čime su izabrani modeli otkriveni bez zavisnosti od E: diska

### GPU offload:
- `auto_gpu_layers: True` → `n_gpu_layers=999` → svi slojevi na GPU (llama.cpp interno kapira)
- Qwen2.5-Coder-7B Q4_K_M (4.36 GB) + KV cache za n_ctx=4096 ≈ 5.5–6 GB → komotno u 10GB VRAM
- CUDA DLL-ovi: `llama_cpp` pip wheel donosi `ggml-cuda.dll`; helper dodaje pip nvidia/cuXX/bin foldere u PATH

---

## 4. Preporuke za inference parametre (faza 6.3)

| Parametar | Trenutno | Preporuka | Razlog |
|---|---|---|---|
| `n_ctx` | 512 | **4096** | 512 seče konverzaciju; Qwen2.5 podržava do 32k; 4k je VRAM/rang balans |
| `max_tokens` | 204 | **1024** | 204 je OK minimum, ali 1024 za pune objašnjene odgovore |
| `n_threads` | 4 | **8** | Fizičkih jezgara ima 8; GPU offload ionako glavni |
| `temperature` | 0.7 | 0.7 | Standard za chat |
| `model_name` | "qwen-7b" | očistiti → default discovery | "qwen-7b" ne mapira se na nijedan fajl |

---

## 5. Embedding modeli (memorija/RAG)

- Trenutno `memory.embedding_model: "stub"` — vektorska memorija koristi pure-Python kNN fallback (radi, sporije).
- U `E:\models` **ne postoji validan embedding model** (mmproj fajlovi su PROJECTOR, ne EMBEDDING; flux je DIFFUSION).
- **Odluka (korak 6.4):** zadržati stub za sada; opciono kasnije dodati mali BGE/E5 GGUF embedding model kad bude potrebno skaliranje znanja. Nepromenjeno za ovaj redizajn.

---

## 6. Verifikacioni plan za modele (faza 6.1/6.2)

```powershell
# 1. Load + generacija headless (bez GUI):
& "C:\Users\Bota\AppData\Local\Programs\Python\Python311\python.exe" main_original.py --test-runtime

# 2. GPU provera tokom generacije (u drugom terminalu):
nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv -l 1

# 3. Otkrivanje modela (quick check):
& "C:\Users\Bota\AppData\Local\Programs\Python\Python311\python.exe" -c "import sys; sys.path.insert(0, r'G:\Projekti\Finalna Aplikacija'); from ai.models.discovery import discover_all_models; print(discover_all_models())"
```
