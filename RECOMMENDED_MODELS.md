# Recommended Models for Offline AI Assistant

**Target hardware:** NVIDIA RTX 3080 10 GB VRAM · 32 GB RAM · Ryzen 7 5700X (8C/16T)
**Runtime:** llama.cpp (llama-cpp-python) · GGUF only
**App features considered:** chat + streaming, **Vision** (needs `mmproj*.gguf` next to the
model — auto-detected), **tool calling** (7 built-in agents), long context (RAG/knowledge),
**memory embeddings** (`memory.embedding_model`, GGUF supported), **STT** (faster-whisper,
local models in `models/voice/stt/<name>`).

## How the app uses hardware

- **Full GPU** (file + mmproj + KV cache ≤ ~9 GB): models up to ~7–8 GB files → best speed.
- **Hybrid GPU+CPU** (app auto-detects optimal GPU layers via `ai.auto_gpu_layers`): with
  32 GB RAM you can run 14–30 GB models with partial offload. MoE models (3.3B active)
  stay fast (~10–20 t/s); dense large models are slow (~2–5 t/s) — fine for background
  agent tasks, not for snappy chat.
- **VRAM is shared**: the STT (Whisper) model also sits in VRAM while transcribing —
  budget ~0.5–1.7 GB for it if you use voice heavily.
- **Context (`ai.n_ctx`)**: default 4096. On 10 GB with a 7–9B Q4 model, 8–16K is a safe
  raise; 32K+ pushes KV cache into hybrid territory.

## Quick-pick summary

| Use case | Top pick | Why |
|---|---|---|
| Best all-round (chat+agents+vision) | **Qwen3.5-9B** UD-Q4_K_XL + mmproj | ~6.9 GB, elite agent/tool benchmarks, 262K ctx |
| Best coding agent | **Qwen3-Coder-30B-A3B** (hybrid) | 3.3B active MoE = fast hybrid, 256K ctx, agentic-coding SOTA |
| Best multimodal | **gemma-4-12B-it QAT** + mmproj + MTP | image **and audio** input, ~7.2 GB, speculative decode |
| Ultra-light everyday | **Qwen3.5-4B** / Llama-3.2-3B | instant responses, always-on model |
| Memory embeddings | **mxbai-embed-large-v1** GGUF | SOTA BERT-large quality, 0.67 GB |
| STT quality upgrade | **whisper large-v3-turbo** | near large-v3 accuracy at turbo speed |

---

## A. Main all-rounders — full GPU (the "daily driver" class)

### 1. Qwen3.5-9B — `unsloth/Qwen3.5-9B-GGUF` (UD-Q4_K_XL 5.97 GB + mmproj-BF16 0.92 GB)
The single best model for this app and GPU. Native vision-language, elite agentic scores
(TAU2-Bench 79.1 — better than much larger models), 262,144 native context, tool-calling
tuned. Apache-2.0. Fits with room for a 16K+ KV cache.
**Use for:** Chat page, all 7 built-in agents, Vision button (OCR, screenshots, diagrams),
knowledge-heavy RAG sessions. The app's name-based capability detection marks it
vision+tools+reasoning automatically. Remember to drop the `mmproj-BF16.gguf` in the same
folder — the app attaches it automatically.

### 2. Ornith-1.5-9B — `ornith-ai/Ornith-1.5-9B-GGUF` (Q4_K_M 5.78 GB + mmproj 0.92 GB)
A Qwen3.5-based 9B tuned specifically for agentic coding and reasoning via RL
self-improvement: SWE-bench Verified 70.6, GPQA-Diamond 86.4 — beats models many times its
size. MIT license (most permissive in this list). Ships an mmproj, so Vision works.
**Use for:** the **Coder** agent, autonomous multi-step agent workflows (Automation),
hard reasoning questions where you want visible thinking.

### 3. gemma-4-12B-it (QAT) — `unsloth/gemma-4-12B-it-qat-GGUF` (UD-Q4_K_XL 6.72 GB + mmproj 0.18 GB + MTP drafter 0.25 GB)
Google's QAT 4-bit = near-bf16 quality at 4-bit size. The only model here with **audio
input** as well as images; 256K context; native tool calling; 140+ languages. The tiny
175 MB mmproj is the lightest vision overhead of any model listed. Includes an MTP drafter
for llama.cpp speculative decoding (faster generation).
**Use for:** multimodal chat, document/screenshot analysis, and any workflow where you
want one model that can do everything reasonably. Excellent quality-per-GB.

### 4. Qwen3.5-4B — `unsloth/Qwen3.5-9B-GGUF` repo family (4B quants ≈ 3 GB + mmproj)
The little sibling: same architecture, same vision, agent-tuned, but nearly instant.
**Use for:** an always-loaded second model for quick questions, the **Planner** agent
(fast plan generation before heavyweight execution), voice-driven quick exchanges.

### 5. Llama-3.1-8B-Instruct — community GGUFs (Q4_K_M ≈ 4.9 GB)
The proven industry standard: rock-solid instruction following, reliable function calling,
predictable behaviour, the widest tooling support of any open model.
**Use for:** a stable fallback general model when you want boring-but-dependable; good
writer agent behaviour (clean prose, follows format instructions).

### 6. Mistral-Nemo-Instruct-2407 (12B) — community GGUFs (Q4_K_M ≈ 7.1 GB)
12B with 128K context and native function calling, designed jointly by Mistral and
NVIDIA; noticeably better general knowledge than 8B class.
**Use for:** long knowledge documents in RAG (128K ctx), Writer agent (strong natural
prose), multilingual tasks.

### 7. Phi-4-mini-instruct (Q6_K_L 3.15 GB) — **already in your `models/llm`**
Keep it: Microsoft's small model punches above its weight on reasoning and structured
output, loads in seconds, and leaves VRAM for the Whisper model.
**Use for:** fast chat, voice sessions (low latency), light Planner duties.

---

## B. Coding specialists — the Coder agent

### 8. Qwen2.5-Coder-7B (Q4_K_M 4.47 GB) — **already in your `models/llm`**
Still the best speed/size coding model for full-GPU use; 128K context.
**Use for:** quick code questions, autocomplete-style help in chat.

### 9. Qwen3-Coder-30B-A3B-Instruct — `unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF` (UD-Q3_K_XL 13.8 GB / Q4_K_M 18.6 GB — hybrid)
Qwen's flagship agentic-coding model: 30.5B total but **only 3.3B active** (MoE), 256K
native context, built for repo-scale understanding and tool loops (CLINE/Qwen-Code
class). With your 32 GB RAM + 10 GB VRAM the app's auto GPU-layer detection gives you a
usable hybrid (~10–20 t/s — MoE stays fast even partially offloaded).
**Use for:** the **Coder** agent on real project tasks (it reads several files via
`read_file`/`search_files` tools and holds them all in context), refactors, "explain this
repo" requests. Text-only — pair it with a vision model when needed.

### 10. Qwen2.5-Coder-14B (Q4_K_M ≈ 9.0 GB — tight full-GPU or light hybrid)
The dense middle child: meaningfully smarter than the 7B, fits (barely) with a small
context window, or comfortably with partial offload.
**Use for:** one step up from your current 7B coder when the 30B is too slow.

---

## C. Reasoning / thinking models — Analyst & Planner agents

### 11. Qwen3-30B-A3B-Thinking-2507 — `unsloth/Qwen3-30B-A3B-Thinking-2507-GGUF` (UD-Q3_K_XL 13.8 GB — hybrid)
Same efficient MoE shell as the Coder, but tuned for deep visible reasoning (AIME25 85.0,
LiveCodeBench 66.0). Fast hybrid thanks to 3.3B active params.
**Use for:** the **Analyst** agent, math/logic questions, multi-step planning. Its long
thinking traces pair perfectly with the app's `reasoning` capability badge.

### 12. DeepSeek-R1-Distill-Qwen-7B (Q4_K_M ≈ 4.6 GB — full GPU)
The classic reasoning distillation — thousands of community fine-tunes target its
output style, and it produces clean step-by-step chains at 7B speed on full GPU.
**Use for:** quick math/logic when you don't want to wake the 30B hybrid.

### 13. Qwen3-4B-Thinking-2507 (Q4_K_M ≈ 2.5 GB — full GPU)
Full thinking mode in a tiny package — near-instant latency.
**Use for:** the **Planner** agent: fast decomposition of goals into task lists before
the heavyweight agents execute.

---

## D. Vision specialists — the Vision button

*All require the `mmproj` file next to the model — the app auto-detects and attaches it.*

### 14. Qwen2.5-VL-7B-Instruct — `ggml-org/Qwen2.5-VL-7B-Instruct-GGUF` (Q4 ~5.7 GB + mmproj ~0.6 GB)
The most battle-tested open vision model: excellent OCR (including handwriting and
documents), chart/diagram understanding, screenshot parsing.
**Use for:** "what's in this picture / read this receipt / explain this error dialog" —
the classic vision-assistant use case, fully on GPU.

### 15. gemma-3-12b-it — `ggml-org/gemma-3-12b-it-GGUF` (Q4 ~7.3 GB + mmproj ~0.8 GB)
Google's previous-gen 12B multimodal — strong world knowledge + image understanding, very
good natural descriptions.
**Use for:** rich image narration, photo Q&A when you prefer Gemma's descriptive style.

### 16. gemma-3-4b-it — `ggml-org/gemma-3-4b-it-GGUF` (Q4 ~2.5 GB + mmproj ~0.8 GB)
Ultra-light vision: ~3.3 GB total leaves most of the GPU free.
**Use for:** a dedicated fast vision model that coexists with a big loaded model.

---

## E. Embedding models — Memory & Knowledge semantic search

*Configure via `memory.embedding_model` in settings; the app's discovery auto-classifies
these filenames as EMBEDDING (excluded from chat, offered for memory).*

### 17. mxbai-embed-large-v1 — `mixedbread-ai/mxbai-embed-large-v1` (GGUF f16 0.67 GB)
SOTA for BERT-large-class embeddings (MTEB 64.68, beats OpenAI's text-embedding-3-large),
1024 dims, supports Matryoshka truncation.
**Use for:** upgrading the app's semantic memory + knowledge RAG from the current stub
embeddings to real retrieval quality. Best single upgrade for Memory/Knowledge pages.

### 18. all-MiniLM-L6-v2 — GGUF conversions (Q8 ≈ 20–45 MB)
The 22M-param legend: near-instant embedding, tiny footprint, 384 dims.
**Use for:** a zero-cost upgrade over the stub that keeps searches instant on huge
knowledge bases.

### 19. nomic-embed-text-v1.5 — GGUF conversions (Q8 ≈ 85–140 MB)
8192-token context — embeds whole document chunks in one pass (vs 512 for the others).
**Use for:** RAG over long documents where chunk integrity matters.

### 20. bge-large-en-v1.5 — GGUF conversions (f16 ≈ 670 MB)
Strong English retrieval specialist, widely used as a RAG default.
**Use for:** an English-knowledge-base alternative to mxbai.

---

## F. STT models — Voice (faster-whisper)

*Place under `models/voice/stt/<name>/`. You already have `base` and `tiny`.*

### 21. whisper small (~460 MB)
Meaningful accuracy jump over `base` (especially accented speech) at still-low latency.
**Use for:** daily voice input quality upgrade.

### 22. whisper large-v3-turbo (~1.6 GB)
Near large-v3 accuracy at ~8x speed on GPU; the current best local STT.
**Use for:** final-answer dictation quality when you use Automatic Listening a lot.
Budget VRAM: 1.6 GB alongside your LLM — fine with a ≤7 GB model.

---

## G. Large hybrid class — when quality > speed

### 23. Qwen3.8-27B — `unsloth/Qwen3.8-27B-GGUF` (UD-Q3_K_XL 13.1 GB + mmproj 0.93 GB — hybrid)
The newest Qwen flagship: native vision, video understanding, best-in-class agentic
reliability. Dense 27B → hybrid is slow (~2–4 t/s) but usable for patient background
agent runs. Q4 does not fit; Q3 XL is the sweet spot.
**Use for:** overnight/long-running agent jobs where you want maximum quality and don't
watch tokens stream.

### 24. Mistral-Small-3.1-24B (Q4_K_M ≈ 14 GB — hybrid)
128K context, vision-capable (ships mmproj in community GGUFs), very good function
calling, European data governance focus.
**Use for:** a one-model hybrid alternative when you want vision + tools + decent speed
in a single bigger model.

### 25. Qwen2.5-14B-Instruct (Q4_K_M ≈ 9.0 GB — full-GPU-tight or hybrid)
The previous-gen 14B all-rounder: excellent general knowledge and Chinese/English
bilingual strength, 128K context.
**Use for:** a mid-size generalist when 7–9B feels weak but 30B-class is too slow.

---

## Suggested setup for your machine

1. **Daily driver:** Qwen3.5-9B UD-Q4_K_XL + mmproj (≈6.9 GB) — covers chat, agents,
   vision, 16K context.
2. **Memory upgrade:** `mxbai-embed-large-v1-f16.gguf` set as `memory.embedding_model`
   (biggest RAG/memory quality win in the app).
3. **Voice:** keep `base`, add `small` (or `large-v3-turbo` if you accept the VRAM share).
4. **Coding sessions:** switch to Qwen3-Coder-30B-A3B hybrid (the app's Unload → Activate
   flow makes switching a two-click operation).
5. **Settings to touch:** `ai.n_ctx` 4096 → 8192/16384 (daily), `ai.auto_gpu_layers`
   already true — leave it; it computes offload layers from your VRAM automatically.

## Notes & caveats

- Sizes are the GGUF **file** sizes; add KV cache (grows with `ai.n_ctx`) and mmproj to
  your VRAM budget.
- Unsloth "UD-*" dynamic quants consistently benchmark ~10% better than standard quants
  at equal size — prefer them when available.
- Model-name convention matters to the app: names containing `vision`/`vl`/`llava` →
  Vision capability; `coder`/`code` → Code; `think`/`r1` → Reasoning; `embed` →
  Embeddings. Keep the original filenames when downloading.
- MoE models (30B-A3B class) are the only >10 GB models that stay *fast* on this
  hardware; dense 24B+ hybrids are background-task territory.



1. Qwen3.5-9B UD-Q4_K_XL - https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/main/Qwen3.5-9B-UD-Q4_K_XL.gguf?download=true
2. Qwen3.5-9B mmproj-BF16 - https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/main/mmproj-BF16.gguf?download=true
3. Qwen3-Coder-30B-A3B-Instruct UD-Q3_K_XL - https://huggingface.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF/resolve/main/Qwen3-Coder-30B-A3B-Instruct-UD-Q3_K_XL.gguf?download=true
4. Qwen3-4B-Thinking-2507 UD-Q4_K_XL - https://huggingface.co/unsloth/Qwen3-4B-Thinking-2507-GGUF/resolve/main/Qwen3-4B-Thinking-2507-UD-Q4_K_XL.gguf?download=true
5. Qwen2.5-VL-7B-Instruct Q4_K_M - https://huggingface.co/ggml-org/Qwen2.5-VL-7B-Instruct-GGUF/resolve/main/Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf?download=true
6. Qwen2.5-VL-7B-Instruct mmproj-F16 - https://huggingface.co/ggml-org/Qwen2.5-VL-7B-Instruct-GGUF/resolve/main/mmproj-Qwen2.5-VL-7B-Instruct-f16.gguf?download=true
7. mxbai-embed-large-v1 F16 - https://huggingface.co/mixedbread-ai/mxbai-embed-large-v1/resolve/main/gguf/mxbai-embed-large-v1-f16.gguf?download=true
8. Ornith-1.5-9B Q4_K_M - https://huggingface.co/ornith-ai/Ornith-1.5-9B-GGUF/resolve/main/Ornith-1.5-9B-Q4_K_M.gguf?download=true
9. Ornith-1.5-9B mmproj-BF16 - https://huggingface.co/ornith-ai/Ornith-1.5-9B-GGUF/resolve/main/mmproj-Ornith-1.5-9B-BF16.gguf?download=true
10. Gemma-4-12B-it QAT UD-Q4_K_XL - https://huggingface.co/unsloth/gemma-4-12B-it-qat-GGUF/resolve/main/gemma-4-12B-it-qat-UD-Q4_K_XL.gguf?download=true
11. Gemma-4-12B-it mmproj-BF16 - https://huggingface.co/unsloth/gemma-4-12B-it-qat-GGUF/resolve/main/mmproj-BF16.gguf?download=true
12. Llama-3.1-8B-Instruct Q4_K_M - https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/main/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf?download=true
13. Mistral-Nemo-Instruct-2407 Q4_K_M - https://huggingface.co/bartowski/Mistral-Nemo-Instruct-2407-GGUF/resolve/main/Mistral-Nemo-Instruct-2407-Q4_K_M.gguf?download=true
14. Qwen2.5-Coder-14B-Instruct Q4_K_M - https://huggingface.co/Qwen/Qwen2.5-Coder-14B-Instruct-GGUF/resolve/main/qwen2.5-coder-14b-instruct-q4_k_m.gguf?download=true
15. Qwen2.5-Coder-7B-Instruct Q4_K_M - https://huggingface.co/unsloth/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf?download=true
16. Qwen3-30B-A3B-Thinking-2507 UD-Q3_K_XL - https://huggingface.co/unsloth/Qwen3-30B-A3B-Thinking-2507-GGUF/resolve/main/Qwen3-30B-A3B-Thinking-2507-UD-Q3_K_XL.gguf?download=true
17. DeepSeek-R1-Distill-Qwen-7B Q4_K_M - https://huggingface.co/bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf?download=true
18. Gemma-3-12B-it Q4_K_M - https://huggingface.co/ggml-org/gemma-3-12b-it-GGUF/resolve/main/gemma-3-12b-it-Q4_K_M.gguf?download=true
19. Gemma-3-12B-it mmproj-F16 - https://huggingface.co/ggml-org/gemma-3-12b-it-GGUF/resolve/main/mmproj-model-f16.gguf?download=true
20. Gemma-3-4B-it Q4_K_M - https://huggingface.co/ggml-org/gemma-3-4b-it-GGUF/resolve/main/gemma-3-4b-it-Q4_K_M.gguf?download=true
21. Gemma-3-4B-it mmproj-F16 - https://huggingface.co/ggml-org/gemma-3-4b-it-GGUF/resolve/main/mmproj-model-f16.gguf?download=true
22. Llama-3.1-8B-Instruct Q4_K_M - https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/main/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf?download=true
23. Qwen2.5-14B-Instruct Q4_K_M - https://huggingface.co/lmstudio-community/Qwen2.5-14B-Instruct-GGUF/resolve/main/Qwen2.5-14B-Instruct-Q4_K_M.gguf?download=true




pojasnjenje:



Klik na naziv/fajl treba direktno da pokrene download, bez traženja fajla po repozitorijumu.

Važna ispravka u odnosu na tvoju listu: nekoliko stavki iz originalnog spiska imaju pogrešna imena/veličine, a faster-whisper modeli nisu GGUF — njih ne treba stavljati u models/llm.

🟢 Moji prvi izbori za RTX 3080 10 GB
#	Model	Quant	Veličina	Download
1	Qwen3.5-9B	UD-Q4_K_XL	5.97 GB	Qwen3.5-9B UD-Q4_K_XL.gguf
2	Ornith-1.5-9B	Q4_K_M	5.78 GB	Ornith-1.5-9B Q4_K_M.gguf
3	Gemma 4 12B IT QAT	UD-Q4_K_XL	6.72 GB	Gemma-4-12B UD-Q4_K_XL.gguf
4	Qwen2.5-VL-7B	Q4_K_M	4.68 GB	Qwen2.5-VL-7B Q4_K_M.gguf

Qwen3.5 repo zaista ima UD-Q4_K_XL od 5.97 GB, a Gemma 4 ima 6.72 GB model + 175 MB mmproj. Qwen2.5-VL Q4_K_M je 4.68 GB.

👁️ MMProj fajlovi za Vision

Ove moraš skinuti pored modela, u isti folder.

Qwen3.5-9B:

Qwen3.5 mmproj-BF16.gguf

Gemma 4:

Gemma 4 mmproj-BF16.gguf

Ornith:

Ornith mmproj-BF16.gguf

Ornith repo eksplicitno sadrži mmproj-Ornith-1.5-9B-BF16.gguf od ~922 MB.

Qwen2.5-VL:

Qwen2.5-VL mmproj-F16.gguf

💻 Coding modeli
Model	Quant	Veličina	Download
Qwen3-Coder-30B-A3B-Instruct	UD-Q3_K_XL	13.8 GB	Qwen3-Coder-30B-A3B UD-Q3_K_XL.gguf
Qwen2.5-Coder-14B-Instruct	Q4_K_M	8.99 GB	Qwen2.5-Coder-14B Q4_K_M.gguf
Qwen2.5-Coder-7B-Instruct	Q4_K_M	~4.5 GB	Qwen2.5-Coder-7B Q4_K_M.gguf

Qwen3-Coder 30B je posebno zanimljiv za tvoju mašinu jer je MoE; provereni UD-Q3_K_XL je 13.8 GB.

Za 10 GB VRAM bih uzeo baš UD-Q3_K_XL, ne Q4.

🧠 Reasoning / Analyst
Model	Quant	Download
Qwen3-30B-A3B-Thinking-2507	UD-Q3_K_XL	Qwen3-30B-A3B Thinking UD-Q3_K_XL.gguf
Qwen3-4B-Thinking-2507	UD-Q4_K_XL	Qwen3-4B Thinking UD-Q4_K_XL.gguf
DeepSeek-R1-Distill-Qwen-7B	Q4_K_M	DeepSeek-R1-Distill-Qwen-7B Q4_K_M.gguf

Qwen3-30B-A3B-Thinking repo potvrđeno postoji i ima UD-Q3_K_XL od 13.8 GB.

👁️ Ostali Vision modeli
Gemma 3 12B

Gemma-3-12B Q4_K_M.gguf

MMProj:

Gemma-3-12B mmproj-model-f16.gguf

Model je ~7.3 GB, a repo zaista uključuje mmproj.

Gemma 3 4B

Gemma-3-4B Q4_K_M.gguf

MMProj:

Gemma-3-4B mmproj-model-f16.gguf

Q4 je 2.49 GB.

🧩 Ostali general-purpose modeli
Llama 3.1 8B

Llama-3.1-8B-Instruct Q4_K_M.gguf

Proverena veličina: 4.92 GB.

Mistral Nemo 12B

Mistral-Nemo-12B Q4_K_M.gguf

Q4_K_M je oko 7.48 GB.

Qwen2.5 14B

Qwen2.5-14B-Instruct Q4_K_M.gguf

Proverena veličina: 8.99 GB.

🧠 Embeddings

Za tvoj memory.embedding_model ja bih stavio mxbai.

mxbai-embed-large-v1

mxbai-embed-large-v1 F16 GGUF

To je 670 MB i originalni MixedBread repo ga direktno nudi u GGUF-u.

Postoji i manji community conversion:

mxbai-embed-large-v1 Q8 GGUF

bge-large-en-v1.5

bge-large-en-v1.5 F32 GGUF

ili, za mnogo manji fajl:

bge-large-en-v1.5 Q8 GGUF

Repo navodi 341 MB za Q8.

🎙️ STT — bitna ispravka

Ovde nemoj skidati GGUF.

Tvoj faster-whisper koristi CTranslate2 modele, ne llama.cpp GGUF modele. Dakle:

models/
└── voice/
    └── stt/
        ├── tiny/
        ├── base/
        ├── small/
        └── large-v3-turbo/

whisper-small i whisper-large-v3-turbo treba preuzeti u formatu koji faster-whisper očekuje, a ne kao .gguf.

🚀 A šta bih ja stvarno instalirao?

Za tvoju 3080 10 GB + 32 GB RAM mašinu ne bih skinuo svih 25. Napravio bih ovaj set:

models/
├── llm/
│   ├── Qwen3.5-9B-UD-Q4_K_XL.gguf
│   ├── mmproj-BF16.gguf
│   │
│   ├── Qwen3-Coder-30B-A3B-Instruct-UD-Q3_K_XL.gguf
│   │
│   ├── Qwen3-4B-Thinking-2507-UD-Q4_K_XL.gguf
│   │
│   └── Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf
│       mmproj-Qwen2.5-VL-7B-Instruct-f16.gguf
│
├── embedding/
│   └── mxbai-embed-large-v1-f16.gguf
│
└── voice/
    └── stt/
        ├── base/
        ├── small/
        └── large-v3-turbo/

To je moj konkretan izbor za tvoj Offline AI Assistant:

🥇 Qwen3.5-9B — default/daily driver
👨‍💻 Qwen3-Coder-30B-A3B — Coder agent
🧠 Qwen3-4B-Thinking — Planner
👁️ Qwen2.5-VL-7B — dedicated Vision fallback
🔎 mxbai-embed-large-v1 — Memory/RAG
🎙️ whisper-small / large-v3-turbo — STT

I još jedna stvar: Qwen3.5-9B + njegov mmproj ti je verovatno dovoljan za većinu Vision + Chat + Agent slučajeva, tako da Qwen2.5-VL ne moraš odmah ni da skidaš. Qwen3.5 repo potvrđuje da je model multimodalan i podržava image-text input.

Ako hoćeš, mogu ti sledeće napraviti jedan download-models.ps1 za Windows koji jednim pokretanjem napravi kompletan models/ folder i skine tačno ovih 6 modela + mmproj fajlove na odgovarajuća mesta.