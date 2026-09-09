# Phase 7 — Hardware Detection & Model Downloader

Hardware capability detection, deterministic model-fit recommendation,
a curated downloadable-model catalog, and a secure streaming downloader
that writes into the canonical user-selected models root.

## Architecture

```
HardwareSnapshot (ai/hardware.py)
    ├─ CPU name/cores/threads, RAM bytes   (psutil, guarded)
    ├─ GPU name/vendor                      (legacy WMI probe — NAME ONLY)
    ├─ VRAM bytes + offload support        (Phase 4 gpu_runtime — NVML)
    └─ disk free bytes                     (models-root drive, NOT "/")
            │
            ▼
ModelVerdict (ai/models/recommendation.py)     [deterministic, pure]
    RECOMMENDED / POSSIBLE / CPU_RECOMMENDED /
    INSUFFICIENT_RESOURCES / INSUFFICIENT_DISK / UNKNOWN
            │
            ▼
Catalog (installer/catalog.py)                [metadata only, curated]
    ├─ DownloadableModel: id, category, url, filename,
    │    size, sha256?, n_ctx, companions (mmproj)
    └─ is_installed(): PHYSICAL file probe (never a manifest)
            │
            ▼
SecureModelDownloader (installer/downloader.py)
    ├─ target = get_model_category_dir(category) / filename   [Phase 3]
    ├─ filename validation (no traversal/absolute/exe)        [Phase 2 reuse]
    ├─ disk-space pre-check (size + 512 MiB margin)
    ├─ streaming write to <name>.part → atomic rename
    ├─ HTTP Range resume (only when server confirms 206)
    └─ size + SHA-256 validation before completion
```

## Hardware detection limitations

* **Single GPU**: VRAM and offload figures describe GPU 0 only (Phase 4
  documented limitation). No multi-GPU splitting is configured or claimed.
* **VRAM unknown** (`vram_bytes == 0`): when pynvml/NVML is unavailable,
  initialization fails, or no NVIDIA GPU exists. Consumers treat this as
  "conservative CPU strategy", never as "no GPU". A warning is surfaced.
* **WMI AdapterRAM is never trusted for VRAM**: it is 32-bit wrapped
  above 4 GB on some systems and reports shared memory on integrated
  GPUs. The legacy installer probe supplies ONLY the GPU name/vendor
  for display. Sizing decisions always use the Phase 4 NVML figure.
* **Optional dependencies never block startup**: psutil, pynvml,
  llama-cpp-python, and WMI are each individually guarded; every probe
  degrades to a deterministic unknown value with a warning instead of
  raising. `detect_hardware_snapshot()` cannot crash the app.
* **Disk space** is measured on the drive of the *user-selected models
  root* (Phase 3 `models.storage_root`), never on `/` or the app drive
  — models may live on any local/external drive. If the probe fails,
  the value is `None` (unknown) and no number is invented.

## Recommendation rules (deterministic)

Decision order in `evaluate_model_fit()` — each step can return early:

1. RAM unknown → `UNKNOWN` (cannot plan anything).
2. Disk: download size + 512 MiB margin > free on models drive →
   `INSUFFICIENT_DISK` (before any bytes are fetched).
3. Memory estimate via the **Phase 4 estimator** for `llm` (file size ×
   1.15 overhead + KV-cache × context); file size for embedding/stt.
   Estimate > 90 % of total RAM → `INSUFFICIENT_RESOURCES`.
4. embedding/stt category, forced-CPU mode, or no offload support →
   `CPU_RECOMMENDED` (RAM already passed).
5. Phase 4 `decide_gpu_layers()` for the GPU plan: FULL_GPU →
   `RECOMMENDED`, PARTIAL_GPU → `POSSIBLE`, CPU_ONLY →
   `CPU_RECOMMENDED`.

**Never** does a verdict claim a model fits merely because the raw file
size is below VRAM — the Phase 4 conservative estimate (overhead factor
plus KV cache) always applies, so recommendation and runtime strategy
can never disagree.

No benchmark or performance numbers are produced.

## Model categories (Phase 3 layout preserved)

```
<models_root>/llm/        chat + vision GGUF (+ mmproj companions, sibling)
<models_root>/embedding/ embedding GGUF
<models_root>/stt/       faster-whisper model folders (legacy voice/stt honored)
```

The catalog never invents a new hierarchy — downloads land in the same
category directories that discovery scans.

## Downloader safety rules

| Rule | Mechanism |
|---|---|
| Streaming only | 1 MB (configurable ≥ 64 KB) chunks; file never in RAM |
| Scoped destination | `get_model_category_dir(category)/filename` only — no API accepts an arbitrary path |
| Filename validation | bare names, no `..` / `/` / `\` / `:` / drive letters / leading `-`; must end `.gguf`/`.bin` |
| Traversal/symlink escape | resolved-path containment inside the category dir; PathValidator hook (injectable) re-uses the Phase 2 boundary |
| No falsely-complete file | writes `<name>.part`; atomic `os.replace` only after validation; discovery ignores `*.part` |
| Disk-space check | free space on the **models-root drive** verified (size + 512 MiB margin) before fetching; insufficient → fail without download |
| Valid file preserved | an existing file with matching size (and checksum, when provided) is never re-downloaded or appended to |
| Resume | HTTP Range attempted only from a confirmed `206`; a `200` answer restarts cleanly (no corruption); a cancelled download leaves a resumable `.part` |
| Size validation | expected size (when known) checked against server report and final file; mismatch → failure, partial removed |
| SHA-256 | verified whenever metadata provides one; mismatch → failure and the corrupt `.part` deleted (optional when metadata has none) |
| Cancellation | stops at the next chunk boundary, closes the file, leaves only `.part` |
| Never executes content | model files are opaque data, only opened for reading/hashing |

### Checksum behavior

* Catalog metadata MAY carry a `sha256`; when present, verification is
  mandatory — a mismatch fails the download and removes the partial.
* When no checksum is provided, the download still validates the
  expected size (when known) and never renames an unvalidated file.
* Nothing is ever "valid merely because it exists": the `is_installed`
  catalog probe checks size (and checksum when present) too.

## Disk-space safety

`check_disk_space(models_root, required)` measures free space **on the
drive of the models root** (creating no directories), compares against
`required + 512 MiB` margin, and returns a human-readable reason when
insufficient. Unknown free-space values pass (with a logged warning)
rather than inventing a number; real write failures still surface at
runtime.

## Model storage ownership

* `models.storage_root` (Phase 3) remains the **only** canonical
  model-storage setting. The downloader, catalog, and UI derive every
  path from `core.paths.get_models_root()` / `get_model_category_dir()`.
* The catalog is **metadata only** — locating installed models stays
  with physical filesystem discovery; a manifest is never required.
* No fixed drive, path, or developer-specific location exists anywhere
  in the Phase 7 code. The models root is always user-selected.
* The installer (Phase 6) never owns model storage and bundles no
  models; nothing here changes that.

## Optional dependency behavior

| Dependency | Missing/failed behavior |
|---|---|
| psutil | CPU counts → 1/1, RAM → 0 (→ `UNKNOWN` verdict), disk → None (allowed, no invented number) |
| pynvml / NVML | VRAM unknown (`0`) + warning; conservative CPU strategy |
| llama-cpp-python | GPU offload unsupported → CPU paths |
| WMI / pywin32 | GPU name/vendor empty; everything else functional |
| faster-whisper | Not required by the downloader (STT entries are ordinary files) |

## Threading / UI

* Downloads run in `CatalogDownloadWorker(QThread)` — the established
  worker pattern — and **never** on the Qt UI thread. Progress arrives
  via Qt signals; the streaming loop lives in the worker thread.
* `ModelManagerDialog` gained a "Downloadable Models" section: catalog
  entries with advisory verdicts, download sizes, disk-space status,
  download/cancel with progress, and errors. The manual URL/filename
  download surface remains for advanced use.
* Cancellation is a clean flag checked at chunk boundaries (no
  `QThread.terminate` for downloads).

## What is deliberately NOT claimed

* No multi-GPU support, selection, or splitting.
* No performance estimates (tokens/sec) — hardware compatibility only.
* No automatic downloads — every download is an explicit user action.
* No "guaranteed to fit" verdicts — conservative estimates only.
