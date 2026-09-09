r"""Installer packaging support — PyInstaller spec + Inno Setup generation.

Generates the deterministic production ``.spec`` for the frozen
application (PHASE 5) and the deterministic Inno Setup ``.iss`` script
that turns the validated onedir output into the production Windows
installer (PHASE 6).

Frozen-build architecture decisions (PHASE 5):

* Mode: **one-folder** (COLLECT).  The application carries Qt, native
  extension modules and potentially CUDA backends — one-folder is the
  technically reliable mode for that payload (fast start, no
  extraction-on-every-launch, DLL dependency resolution is stable).
* Entry point: ``run.py`` (the application launcher).
* ``console=False`` for the production GUI build; diagnostics remain
  available through the application's rotating file logs under the
  user-data root.
* Data files: only the runtime-required SQL migrations
  (``database/migrations/*.sql``) — the database layer resolves them
  relative to the bundled module directory, so the destination mirrors
  that layout under the PyInstaller runtime root.
* Hidden imports: kept minimal and justified — statically analyzed
  imports are NOT duplicated here.  Only (a) Windows COM support used via
  top-level ``win32com`` imports, and (b) optional runtime backends that
  are actually installed in the build environment (llama_cpp,
  faster-whisper, sounddevice, scipy, pyttsx3, pynvml) are added
  conditionally, preserving the project's graceful-degradation contract
  when they are absent.
* Native DLLs: collected by PyInstaller's own hooks (PySide6, numpy,
  psutil, pywin32 via ``pyinstaller-hooks-contrib``) — no blind DLL
  copying and no machine-specific paths.
* Models are NEVER bundled: model storage is the user-selected
  ``models.storage_root`` (PHASE 3) and stays external to the executable.
* UPX disabled: deterministic builds, no native-DLL compression risk.
* Version metadata: a PyInstaller version file is generated from the
  canonical ``pyproject.toml`` version (single source of truth) — never
  a second competing version configuration.

Reproducible build process::

    python -m installer.packager          # writes offline_ai_frozen.spec (+ version file)
    python -m PyInstaller --noconfirm --clean offline_ai_frozen.spec

Installer build (PHASE 6, after the PyInstaller step above)::

    python -m installer.packager --inno    # writes installer/OfflineAI.iss
    ISCC.exe installer\OfflineAI.iss       # -> installer_output/OfflineAI_Setup_3.1.0.exe

Inno Setup script contract (PHASE 6):

* Payload: the COMPLETE validated onedir output ``dist/OfflineAI/``
  (``OfflineAI.exe`` + ``_internal\\...``) — packaged recursively,
  never a one-file executable, never hand-picked DLLs.
* Install directory: ``{autopf}\\OfflineAI`` (architecture-aware
  Program Files), user-changeable.
* Models are NEVER installed, bundled or configured by the installer:
  the user-selected ``models.storage_root`` (PHASE 3) is chosen in the
  application's own first-run wizard (LocationsPage) and persisted via
  ``set_models_root()``.  The installer deliberately contains NO model
  location UI and NO model-path configuration — it never becomes a
  competing source of truth.
* Uninstall removes application binaries, shortcuts and uninstall
  registration only.  User data (``%LOCALAPPDATA%\\OfflineAI`` and the
  user-selected models root) is NEVER deleted — the recursive
  ``{app}`` cleanup touches only the install directory, which never
  contains user data or models.
* Version: ``AppVersion`` is generated from the canonical
  ``pyproject.toml`` version — never a second maintained value.
* Determinism: byte-identical output for identical inputs; runtime
  build paths are emitted as relative paths resolved against the
  ``.iss`` location, so the generated script contains no
  machine-specific absolute paths.

Smoke test (headless validation of the frozen executable)::

    OFFLINE_AI_SMOKE_TEST=1 OFFLINE_AI_TEST_MODE=1 QT_QPA_PLATFORM=offscreen <dist>/OfflineAI/OfflineAI.exe
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    from PyInstaller.utils.hooks import collect_all

    pyside6_datas, pyside6_binaries, pyside6_hiddenimports = collect_all("PySide6")
    pyside6_datas = list(pyside6_datas) if pyside6_datas else []
    pyside6_binaries = list(pyside6_binaries) if pyside6_binaries else []
    pyside6_hiddenimports = (
        list(pyside6_hiddenimports) if pyside6_hiddenimports else []
    )
except ImportError:
    pyside6_datas = []
    pyside6_binaries = []
    pyside6_hiddenimports = []


# ---------------------------------------------------------------------------
# Production spec configuration (single source of packaging truth)
# ---------------------------------------------------------------------------

#: Application entry point (relative to the project root / spec dir).
PRODUCTION_ENTRY_POINT = "run.py"

#: Output name of the generated production spec (project root).
PRODUCTION_SPEC_FILENAME = "offline_ai_frozen.spec"

#: Frozen application name — must match the Phase 5 COLLECT output dir.
APP_NAME = "OfflineAI"

#: PyInstaller onedir output consumed by the Inno Setup script, relative
#: to the project root.  The generated .iss resolves it against its own
#: location via {%SOURCEPATH} so the script stays relocatable with the
#: repository — no absolute, machine-specific paths.
ONEDIR_SOURCE_REL = Path("dist") / APP_NAME

#: Output directory for the compiled installer (.iss OutputDir), anchored
#: at the project root (the .iss emits it relative to its own location).
INSTALLER_OUTPUT_DIR = "installer_output"

#: Generated Inno Setup script location (deterministic, committed layout).
INNO_SCRIPT_PATH = Path("installer") / f"{APP_NAME}.iss"

#: Data files required at frozen runtime: (source glob, destination dir).
#: The database layer loads migrations from ``<module dir>/migrations``,
#: which inside the bundle resolves to ``<PyInstaller runtime root>``.
PRODUCTION_DATAS: list[tuple[str, str]] = [
    ("database/migrations/*.sql", "database/migrations"),
]

#: Optional runtime backends — bundled only when installed in the build
#: environment (find_spec at spec-generation time).  Absent backends keep
#: the application's existing graceful degradation (stub/TEST_MODE paths).
OPTIONAL_RUNTIME_PACKAGES: list[str] = [
    "llama_cpp",
    "faster_whisper",
    "sounddevice",
    "scipy",
    "pyttsx3",
    "pynvml",
]

#: Always-required hidden imports not discoverable by static analysis.
#: win32com/win32timezone are pulled in through top-level ``win32com.client``
#: usage in installer.hardware (pywin32 hook covers the rest).
REQUIRED_HIDDEN_IMPORTS: list[str] = [
    "win32com",
    "win32timezone",
]

#: Development-only modules excluded from the frozen build.
PRODUCTION_EXCLUDES: list[str] = [
    "tkinter",
    "unittest",
    "pytest",
    "tests",
    "docs",
    "setuptools",
    "pip",
]


#: Dev-only packaging artifacts never shipped in the installer payload.
#: (Documentation only — the [Files] entry packages exactly the onedir
#: directory produced by Phase 5, which by construction contains none
#: of these.)
INSTALLER_NEVER_PACKAGES: tuple[str, ...] = (
    "models",
    "user_data",
    "config",
    "logs",
    "tests",
    "pytest cache",
    "source repository files",
)



@dataclass(frozen=True, slots=True)
class PackageSpec:
    """Metadata for a packaged installer build."""

    app_name: str
    version: str
    entry_point: str
    icon: Path | None = None
    include_pyqt: bool = False
    console: bool = False
    additional_files: list[tuple[str, str]] = field(default_factory=list)
    target_dir: Path = Path("dist")
    work_dir: Path = Path("build")
    spec_file: Path = field(default_factory=lambda: Path("installer.spec"))


@dataclass(frozen=True, slots=True)
class InnoSetupScript:
    """Generated Inno Setup script content."""

    script_text: str
    output_path: Path


def _optional_hidden_imports() -> list[str]:
    """Hidden imports for optional backends actually present at build time.

    Deterministic per environment: ``find_spec`` decides.  Packages that are
    not installed are omitted entirely (adding them would break the build;
    omitting them preserves the runtime's guarded fallbacks).
    """
    installed = [
        name
        for name in OPTIONAL_RUNTIME_PACKAGES
        if importlib.util.find_spec(name) is not None
    ]
    if installed:
        logger_note = ", ".join(installed)
        print(f"[packager] optional backends bundled: {logger_note}")
    else:
        print("[packager] no optional backends installed — frozen build "
              "will rely on built-in stub/TEST_MODE fallbacks")
    return installed


def _quote(value: str) -> str:
    """Escape *value* for a single-quoted Python string literal in the spec."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def build_pyinstaller_spec(spec: PackageSpec) -> str:
    """Generate the deterministic PyInstaller ``.spec`` file content.

    One-folder layout, GUI console mode (``spec.console``), minimal
    justified hidden imports, migrations as the only datas, no UPX, and
    version metadata from the canonical application version.
    """
    datas = list(PRODUCTION_DATAS) + [
        (src, dst) for src, dst in spec.additional_files
    ]
    hidden = list(REQUIRED_HIDDEN_IMPORTS) + _optional_hidden_imports()

    lines: list[str] = [
        "# -*- mode: python ; coding: utf-8 -*-",
        (
            f"# Auto-generated by installer.packager for {spec.app_name} "
            f"v{spec.version} — DO NOT EDIT by hand; regenerate instead."
        ),
        (
            "# One-folder production build. Regenerate with: "
            "python -m installer.packager"
        ),
        "",
        "block_cipher = None",
        "",
        "a = Analysis(",
        f"    ['{_quote(spec.entry_point)}'],",
        "    pathex=['.'],",
        "    binaries=[],",
        "    datas=[",
    ]
    for src, dst in datas:
        lines.append(f"        ('{_quote(src)}', '{_quote(dst)}'),")
    lines.extend([
        "    ],",
        "    hiddenimports=[",
    ])
    for name in hidden:
        lines.append(f"        '{_quote(name)}',")
    lines.extend([
        "    ],",
        "    hookspath=[],",
        "    hooksconfig={},",
        "    runtime_hooks=[],",
        "    excludes=[",
    ])
    for name in PRODUCTION_EXCLUDES:
        lines.append(f"        '{_quote(name)}',")
    lines.extend([
        "    ],",
        "    noarchive=False,",
        ")",
        "",
        "pyz = PYZ(a.pure)",
        "",
        "exe = EXE(",
        "    pyz,",
        "    a.scripts,",
        "    [],",
        "    exclude_binaries=True,",
        f"    name='{_quote(spec.app_name)}',",
        "    debug=False,",
        "    bootloader_ignore_signals=False,",
        "    strip=False,",
        "    upx=False,",
        "    console=" + ("True" if spec.console else "False") + ",",
        "    disable_windowed_traceback=False,",
        "    argv_emulation=False,",
        "    target_arch=None,",
        "    codesign_identity=None,",
        "    entitlements_file=None,",
        f"    icon={('None') if spec.icon is None else repr(str(spec.icon))},",
        "    version='app_version_info.txt',",
        ")",
        "",
        "coll = COLLECT(",
        "    exe,",
        "    a.binaries,",
        "    a.zipfiles,",
        "    a.datas,",
        "    strip=False,",
        "    upx=False,",
        "    upx_exclude=[],",
        f"    name='{_quote(spec.app_name)}',",
        ")",
    ])

    return "\n".join(lines) + "\n"


def build_version_info_text(app_name: str, version: str) -> str:
    """Generate a PyInstaller version-file (VSVersionInfo) as text.

    Reuses the canonical application version (``pyproject.toml``) — never
    a second independent version source.
    """
    parts = version.split(".")
    numeric = [int(p) for p in parts if p.isdigit()][:4]
    while len(numeric) < 4:
        numeric.append(0)
    filevers = tuple(numeric)
    strvers = ".".join(str(n) for n in filevers)
    return f"""# Generated by installer.packager from the canonical application version.
# VSVersionInfo for {app_name} {version}
VSVersionInfo(
    ffi=FixedFileInfo(
        filevers={filevers!r},
        prodvers={filevers!r},
        mask=0x3F,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo([
            StringStruct('CompanyName', 'OfflineAI'),
            StringStruct('FileDescription', '{app_name}'),
            StringStruct('FileVersion', '{strvers}'),
            StringStruct('InternalName', '{app_name}'),
            StringStruct('OriginalFilename', '{app_name}.exe'),
            StringStruct('ProductName', '{app_name}'),
            StringStruct('ProductVersion', '{version}'),
        ]),
        VarFileInfo([VarStruct('Translation', [1033, 1200])]),
    ],
)
"""


def write_pyinstaller_spec(spec: PackageSpec, path: Path | None = None) -> Path:
    """Write the generated spec file (and its companion version file).

    Defaults to ``spec.spec_file`` if *path* is not provided.  The PyInstaller
    version metadata file (``app_version_info.txt``) is written next to the
    spec so the build picks it up from the spec directory.
    """
    out = path or spec.spec_file
    out.parent.mkdir(parents=True, exist_ok=True)
    content = build_pyinstaller_spec(spec)
    out.write_text(content, encoding="utf-8")
    version_file = out.parent / "app_version_info.txt"
    version_file.write_text(
        build_version_info_text(spec.app_name, spec.version), encoding="utf-8"
    )
    return out


# ---------------------------------------------------------------------------
# Production spec entry point (reproducible build process)
# ---------------------------------------------------------------------------


def get_canonical_version() -> str:
    """Return the canonical application version.

    Single source of truth: ``pyproject.toml`` ``[project] version``.
    Falls back to a safe default only when the file is unreadable (never
    invents a competing version elsewhere).
    """
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        for line in pyproject.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("version"):
                _, _, value = stripped.partition("=")
                return value.strip().strip("'\"")
    except OSError:
        pass
    return "0.0.0"


def write_production_spec(project_root: Path | None = None) -> Path:
    """Write the deterministic production spec for the real application.

    Returns the spec path.  Intended invocation (from the project root)::

        python -m installer.packager
    """
    root = (project_root or Path(__file__).resolve().parent.parent).resolve()
    spec = PackageSpec(
        app_name="OfflineAI",
        version=get_canonical_version(),
        entry_point=PRODUCTION_ENTRY_POINT,
        icon=None,  # no application icon exists; none is fabricated
        console=False,
        spec_file=root / PRODUCTION_SPEC_FILENAME,
    )
    return write_pyinstaller_spec(spec)


def build_inno_setup_script(
    app_name: str,
    version: str,
    app_filename: str | None = None,
    install_dir: str | None = None,
    output_path: Path | None = None,
) -> InnoSetupScript:
    """Generate the deterministic Inno Setup ``.iss`` script (PHASE 6).

    The script packages the complete Phase 5 PyInstaller onedir output
    (``dist/<app_name>`` — the launcher .exe plus the whole ``_internal``
    tree), installs it to *install_dir* (default: architecture-aware
    Program Files, user-changeable), creates Start Menu / optional
    Desktop shortcuts for the launcher executable, and registers the
    application for Add/Remove Programs.

    Deliberately NOT done by the installer (PHASE 6 architecture):

    * No model location UI and no model-path persistence — the
      application's own first-run wizard (LocationsPage) collects the
      choice and persists it through ``set_models_root()`` into the
      canonical ``models.storage_root`` setting.  The installer never
      becomes a competing source of truth.
    * No user-data directory creation — the application creates its
      ``%LOCALAPPDATA%\\OfflineAI`` layout lazily at runtime, under the
      actually-logged-in user account, not under the elevated
      installer account.
    * No user-data deletion on uninstall — ``[UninstallDelete]`` only
      cleans the application install directory, which never contains
      user data or models.
    """
    filename = app_filename or app_name.replace(" ", "")
    # Architecture-aware Program Files install directory, user-changeable
    # ({autopf} resolves to the 64-bit Program Files on x64 installs).
    # Never a fixed drive, never a developer-specific path.
    if install_dir is None:
        install_dir = rf"{{autopf}}\{filename}"
    # Source paths are RELATIVE and resolved by the Inno Setup
    # preprocessor against the .iss location ({#SourcePath} = directory
    # of this script), so the generated script is relocatable with the
    # repository and contains no machine-specific absolute paths.
    onedir_source = "{#SourcePath}\\..\\dist\\" + filename
    safe_name = filename  # already space-free; used in output filename
    lines = [
        f"; Auto-generated Inno Setup script for {app_name} — DO NOT EDIT by hand.",
        "; Generated by installer.packager from the canonical pyproject version.",
        "; Rebuild with: python -m installer.packager --inno",
        f"; Application version: {version}",
        "",
        "[Setup]",
        "; Stable AppId: survives version upgrades and binds them to the same",
        "; application entry in Add/Remove Programs.",
        f"AppId={{{{8D4D4AE1-9C2A-4A01-8C40-4B4862A9B3C0}}}}_{safe_name}",
        f"AppName={app_name}",
        f"AppVersion={version}",
        "; Company/publisher metadata (Add/Remove Programs display only).",
        "AppPublisher=OfflineAI",
        "; Architecture-aware Program Files; the user may change it.",
        f"DefaultDirName={install_dir}",
        "; Windows x64-only build (PyInstaller 64-bit payload).",
        "ArchitecturesAllowed=x64compatible",
        "ArchitecturesInstallIn64BitMode=x64compatible",
        "; Normal Windows application installer privileges.  The INSTALLED",
        "; application does not require elevation for its own operation.",
        "PrivilegesRequired=admin",
        "; Least-privilege option (per-user installs) stays available.",
        "PrivilegesRequiredOverridesAllowed=dialog commandline",
        f"DefaultGroupName={app_name}",
        "DisableProgramGroupPage=yes",
        f"UninstallDisplayName={app_name}",
        f"UninstallDisplayIcon={{app}}\\{filename}.exe",
        f"OutputDir={{#SourcePath}}\\..\\{INSTALLER_OUTPUT_DIR}",
        f"OutputBaseFilename={safe_name}_Setup_{version}",
        "Compression=lzma2/max",
        "SolidCompression=yes",
        "; Deterministic builds: no timestamp leak, fixed installer metadata.",
        "TimeStampRounding=0",
        "WizardStyle=modern",
        "",
        "[Languages]",
        "Name: \"english\"; MessagesFile: \"compiler:Default.isl\"",
        "",
        "[Tasks]",
        (
            "Name: \"desktopicon\"; Description: \"{cm:CreateDesktopIcon}\"; "
            "GroupDescription: \"{cm:AdditionalIcons}\"; Flags: unchecked"
        ),
        "",
        "[Files]",
        "; Complete Phase 5 onedir payload, packaged recursively: the",
        f"; launcher {filename}.exe plus the entire _internal tree.",
        "; The launcher entry has no skipif... flag: a missing PyInstaller",
        "; output must abort the compile loudly instead of shipping a",
        "; broken installer.",
        (
            f"Source: \"{onedir_source}\\{filename}.exe\"; DestDir: \"{{app}}\"; "
            "Flags: ignoreversion"
        ),
        (
            f"Source: \"{onedir_source}\\_internal\\*\"; DestDir: \"{{app}}\\_internal\"; "
            "Flags: ignoreversion recursesubdirs createallsubdirs "
            "skipifsourcedoesntexist"
        ),
        "",
        "[Icons]",
        f"Name: \"{{group}}\\{app_name}\"; Filename: \"{{app}}\\{filename}.exe\"",
        f"Name: \"{{group}}\\Uninstall {app_name}\"; Filename: \"{{uninstallexe}}\"",
        (
            f"Name: \"{{autodesktop}}\\{app_name}\"; Filename: \"{{app}}\\{filename}.exe\"; "
            "Tasks: desktopicon"
        ),
        "",
        "[Run]",
        (
            f"Filename: \"{{app}}\\{filename}.exe\"; Description: \"Launch {app_name}\"; "
            "Flags: nowait postinstall skipifsilent"
        ),
        "",
        "[UninstallDelete]",
        "; PHASE 6 uninstall contract: remove ONLY application binaries under",
        "; {app}.  User data (%LOCALAPPDATA%\\OfflineAI: projects, knowledge,",
        "; configuration, logs) and the user-selected models root are NEVER",
        "; deleted by the uninstaller.  The recursive {app} cleanup is safe",
        "; because models and user data are architecturally never installed",
        "; under {app}.",
        "Type: filesandordirs; Name: \"{app}\"",
        "",
        "; No model-location UI, no model-path persistence, no user-data",
        "; creation, no telemetry, no extra registry integrations — by design",
        "; (see the PHASE 6 installer architecture).",
    ]

    script_text = "\n".join(lines) + "\n"
    if output_path is None:
        # Deterministic default INSIDE the repo layout (never the CWD —
        # the application must not depend on the working directory).
        output_path = Path(__file__).resolve().parent / f"{APP_NAME}.iss"
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(script_text, encoding="utf-8", newline="\n")
    return InnoSetupScript(script_text=script_text, output_path=out)


def generate_installer_package(
    spec: PackageSpec,
    inno_output: Path | None = None,
) -> tuple[str, InnoSetupScript]:
    """Generate both the PyInstaller spec and Inno Setup script.

    Returns the spec content string and the InnoSetupScript object.
    """
    spec_content = build_pyinstaller_spec(spec)
    write_pyinstaller_spec(spec)

    iss = build_inno_setup_script(
        app_name=spec.app_name,
        version=spec.version,
        app_filename=spec.app_name.replace(" ", ""),
        output_path=inno_output,
    )

    return spec_content, iss


def write_production_inno_script(project_root: Path | None = None) -> Path:
    """Write the deterministic production Inno Setup script.

    Intended invocation (from the project root)::

        python -m installer.packager --inno

    The script targets the real application: canonical version from
    ``pyproject.toml``, the Phase 5 onedir output as payload, the
    committed ``installer/OfflineAI.iss`` location.
    """
    root = (project_root or Path(__file__).resolve().parent.parent).resolve()
    return build_inno_setup_script(
        app_name=APP_NAME,
        version=get_canonical_version(),
        output_path=root / INNO_SCRIPT_PATH,
    ).output_path


def main(argv: list[str] | None = None) -> int:
    """CLI entry: regenerate the deterministic production artifacts.

    Usage (from the project root)::

        python -m installer.packager           # PyInstaller spec
        python -m installer.packager --inno    # Inno Setup script
        python -m installer.packager --all     # both
    """
    args = list(sys.argv[1:] if argv is None else argv)
    # --inno: only the installer script; --all: both; no flags: the
    # PyInstaller spec (Phase 5 default behaviour).
    if "--inno" in args:
        iss_path = write_production_inno_script()
        print(f"[packager] Inno Setup script written: {iss_path}")
        print(
            "[packager] compile with: "
            "ISCC.exe \"" + str(iss_path) + "\""
        )
        return 0
    if "--all" in args:
        iss_path = write_production_inno_script()
        print(f"[packager] Inno Setup script written: {iss_path}")
    spec_path = write_production_spec()
    print(f"[packager] production spec written: {spec_path}")
    print(
        "[packager] build with: "
        "python -m PyInstaller --noconfirm --clean "
        f"{spec_path.name}"
    )
    if "--all" in args:
        print(
            "[packager] installer with: ISCC.exe \"" + str(iss_path) + "\""
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
