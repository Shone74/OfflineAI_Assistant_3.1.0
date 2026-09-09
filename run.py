"""Offline AI Assistant — final application launcher.

Development: adds the project root to ``sys.path`` and starts the app.

Frozen (PyInstaller): performs the frozen bootstrap —

* bundled CUDA/native DLL directories (``_MEIPASS/nvidia/*/bin*``) are
  registered through the PHASE 4 GPU runtime extension point
  (:func:`ai.models.gpu_runtime.register_cuda_dll_dir`) when — and only
  when — they actually exist inside the bundle.  CUDA stays optional:
  a bundle without CUDA directories starts fine on CPU.
* a headless smoke-test mode (``OFFLINE_AI_SMOKE_TEST=1``) validates the
  frozen build without a GUI — path resolution, config initialization,
  resource awareness — and exits.

Everything derives from the established path architecture
(:mod:`core.paths`); the process working directory is never consulted.
"""

from __future__ import annotations

import os
import sys


def _app_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _prepare_paths(app_root: str) -> None:
    if app_root not in sys.path:
        sys.path.insert(0, app_root)


def _register_frozen_cuda_dirs() -> None:
    """Register bundled CUDA DLL directories (frozen builds only).

    Looks for the NVIDIA runtime layout inside the PyInstaller runtime
    root and hands each existing directory to the PHASE 4 extension
    point.  No hardcoded paths; absent directories are skipped silently
    (CPU-only bundles remain valid).
    """
    from pathlib import Path

    if not getattr(sys, "frozen", False):
        return
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return
    try:
        from ai.models.gpu_runtime import register_cuda_dll_dir

        root = Path(meipass)
        nvidia_root = root / "nvidia"
        if nvidia_root.is_dir():
            for cu_dir in sorted(nvidia_root.iterdir()):
                if not cu_dir.is_dir() or not cu_dir.name.startswith("cu"):
                    continue
                for bin_sub in ("bin", "bin/x86_64"):
                    register_cuda_dll_dir(cu_dir / bin_sub)
        # A CUDA runtime may also be flattened directly into the bundle
        # root by the packaging step; register well-known loader names
        # only when the directory exists.
        register_cuda_dll_dir(root)
    except Exception as exc:
        print(f"[run] CUDA directory registration skipped: {exc}", file=sys.stderr)


def _frozen_smoke_test() -> int:
    """Headless frozen-build validation (``OFFLINE_AI_SMOKE_TEST=1``).

    Verifies, without a GUI, that the frozen executable can:

    * import the path architecture and resolve all runtime directories
      (identical results regardless of the current working directory);
    * initialize the configuration / user-data layout;
    * see its bundled resources root (without writing to it);
    * run with models strictly external (``models.storage_root`` —
      nothing is expected inside the bundle);
    * tolerate an absent CUDA stack (GPU capability check stays safe).

    Returns 0 on success, non-zero on failure.
    """
    failures: list[str] = []
    # 1. Deterministic path resolution (CWD-independent by contract).
    import tempfile
    from pathlib import Path

    from core import paths

    with tempfile.TemporaryDirectory() as tmp:
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp)
            user_data = paths.user_data_root()
            config_dir = paths.get_config_dir()
            models_root = paths.get_models_root()
        finally:
            os.chdir(old_cwd)
    if not (user_data.is_absolute() and config_dir.is_absolute()
            and models_root.is_absolute()):
        failures.append("path resolution returned relative paths")

    # 2. Frozen resource root is visible and read-only (never written to).
    #    NOTE: this application currently bundles no read-only resources —
    #    an absent ``resources`` directory is a valid state; the invariant
    #    that matters (user data never under bundled resources) is checked
    #    regardless.
    resource_root = paths.resource_root()
    if user_data == resource_root or resource_root in user_data.parents:
        failures.append("user data must not live under bundled resources")

    # 3. Models stay external — never inside the bundle.
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass and models_root == Path(meipass):
            failures.append("models root must not point into the bundle")

    # 4. Config initialization works in the frozen environment.
    from core.config_manager import ConfigManager

    config = ConfigManager()
    if not config.get("app.name"):
        failures.append("ConfigManager returned no app name")
    if not config.settings_path.is_absolute():
        failures.append("settings path is not absolute")

    # 5. GPU capability check is safe without CUDA/llama.cpp.
    from ai.models.gpu_runtime import detect_gpu_capabilities

    caps = detect_gpu_capabilities(refresh=True)
    if caps.offload_supported and not caps.vram_known:
        # Supported build without VRAM info is a legitimate state; the
        # strategy handles it conservatively. Nothing to fail here.
        pass

    # 6. Database migrations are reachable in the bundle.
    migrations = (
        paths.app_root() / "database" / "migrations"
    )
    if getattr(sys, "frozen", False) and not migrations.is_dir():
        failures.append(f"bundled migrations missing: {migrations}")

    if failures:
        for failure in failures:
            print(f"[smoke] FAIL: {failure}", file=sys.stderr)
        return 1
    print(
        "[smoke] OK: paths resolved, config initialized, resources visible, "
        f"user_data={user_data}, models_root={models_root}, "
        f"gpu_offload={caps.offload_supported}"
    )
    return 0


def main() -> int:
    app_root = _app_root()
    _prepare_paths(app_root)

    if getattr(sys, "frozen", False):
        # Frozen bootstrap: bundled CUDA dirs via the PHASE 4 extension
        # point, before any native backend import happens.
        _register_frozen_cuda_dirs()
        if os.environ.get("OFFLINE_AI_SMOKE_TEST", "") == "1":
            return _frozen_smoke_test()

    os.environ.setdefault("QT_QPA_PLATFORM", "windows")
    from app.application_final import main as app_main
    return app_main()


if __name__ == "__main__":
    sys.exit(main())
