# START HERE — Offline AI Assistant

## Pokretanje
```
python run.py
```
(dupli klik na `run.py` takođe radi)

## Prvo pokretanje
Kreiraju se folderi u `%LOCALAPPDATA%\OfflineAI\`:
- `config\settings.json`
- `data\assistant.db`
- `logs\`
- `models\llm\`

Pa se pokreće instalacioni wizard (7 koraka). Ako nema modela, aplikacija
radi u limited (stub) modu — dodaj model kroz Models stranicu.

## Modeli
Stavi `.gguf` fajl u jedan od:
```
%LOCALAPPDATA%\OfflineAI\models\llm\       (default)
models\llm\                                 (folder projekta)
```
Ollama/LM Studio modeli se otkrivaju automatski.

Preporučeno: Qwen2.5-Coder-7B Q4_K_M (~4.4 GB).

## GPU (opciono)
Aplikacija sama koristi NVIDIA GPU ako je dostupan CUDA-enabled
llama-cpp-python (vidi README §GPU ubrzanje).

## Problemi?
- Logovi: `%LOCALAPPDATA%\OfflineAI\logs\`
- Testovi: `pytest tests/` (92 testa)
- Runtime test: `python main_original.py --test-runtime`
- Dokumentacija: `docs/` folder (plan, status, dizajn, modeli)
