# Phase 8 — Project Integration

How the Phase 1–7 architecture is consumed by the application. This
document records the final integration relationships after Phase 8.

## Integration relationships

```
Application (app.application.ApplicationManager.start)
→ core.paths (canonical app/resource/user-data/model roots)
→ user data (%LOCALAPPDATA%\OfflineAI: config, data, logs, plugins, knowledge_docs)

Models
→ models.storage_root (canonical, user-selected)
→ core.paths.get_model_category_dir(category)  (llm / embedding / stt)
→ discovery (physical files only — no manifest)
→ loading (ai.models.model_manager.ModelManager)
→ downloader (installer.downloader.SecureModelDownloader + catalog)

GPU
→ ai.models.gpu_runtime (Phase 4 — the only NVML/CUDA consumer)

Hardware
→ ai.hardware.HardwareSnapshot (Phase 7 — the only UI-facing hardware API)

Projects
→ project.manager.ProjectManager + PathValidator (Phase 2)
→ workspace enumeration: link-safe, read-authorized
→ workspace deletion: ONLY through ProjectManager.delete_workspace_files

Knowledge
→ knowledge.knowledge_base.KnowledgeBase
→ indexing: link-safe walk, skips .part/hidden, read-authorized
```

## Runtime propagation contract

Changing the models location MUST update `models.storage_root` and
re-point the runtime `ModelManager` at the `llm` category dir under the
new root — without copying, moving, or deleting model files:

| Surface | Persists via | Re-points runtime via |
|---|---|---|
| Welcome wizard (InstallationPage) | `set_models_root()` | restart (first run) |
| Settings → ModelStatusTab | `set_models_root(config=…)` | `ScanThread` → `set_models_dir(root/llm)` |
| ModelsPage "Select Models Folder" | `set_models_root()` + `CONFIG_CHANGED` | `set_models_dir(root/llm)` |
| MainWindow `CONFIG_CHANGED` handler | (consumer) | `models.storage_root` → `_apply_models_root_change()` |

Legacy `ai.models_dir` remains readable (compatibility mirror written by
`set_models_root`, parent-normalized to the root) until Phase 9.

## Consumers of the shared hardware/GPU abstractions

| Consumer | Uses |
|---|---|
| `tools/system_tools.py` `system_info` GPU label | `ai.hardware.detect_hardware_snapshot()` (Phase 8: replaced its private WMI AdapterRAM probe) |
| `ui/model_manager_dialog.py` | `HardwareSnapshot` + `catalog_status()` |
| Model loading | `ai.models.gpu_runtime.decide_gpu_layers()` |
| Model recommendation | `ai.models.recommendation.evaluate_model_fit()` |
| Installer hardware probe (`installer/hardware.py`) | legacy name/vendor hint only; VRAM never trusted (32-bit wrap > 4 GB) |

## Known documented behavior

* `run.py`'s smoke test deliberately `chdir`s to a temp dir to VERIFY
  CWD independence — the only sanctioned `os.chdir` in the project.
* Windows symlink-escape live tests skip without developer mode; the
  containment logic is covered by resolved-path assertions.
* The dev machine's own `settings.json` may point `models.storage_root`
  at a historical location — the architecture honors the user's stored
  choice; no code path overrides it.
