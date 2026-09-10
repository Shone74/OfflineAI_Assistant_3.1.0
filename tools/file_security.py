"""File security layer — path validation and traversal prevention.

Provides reusable path validation for all file-based tools.  Distinguishes
between READ and WRITE allowed roots.

Design:
    * When the policy is **disabled** (``enabled=False``) the validator
      allows all paths after basic sanitisation (backward-compatible).
    * When the policy is **enabled** and roots are configured, paths must
      resolve inside one of them.
    * When the policy is **enabled** but no write roots are configured,
      write operations are denied with a clear error (the "Unconfigured"
      state described in the security model).  Read operations remain
      allowed so that existing read-only tools continue to function.
    * Path traversal (``..`` components) is always rejected at the raw
      string level before resolution.
    * Symlinks that resolve outside allowed roots are rejected.
    * Null bytes and other dangerous characters are blocked.
    * Windows drive letters and UNC paths are handled.

Deterministic path resolution (no CWD dependency):
    * Absolute input paths are validated directly.
    * Relative input paths are resolved against the validator's explicit
      ``base_dir`` (the application's deterministic user-data root) —
      NEVER against the process CWD.
    * Relative input paths are REJECTED when no ``base_dir`` is
      configured, rather than silently becoming CWD-dependent.
    * Configured security roots must be ABSOLUTE.  Relative roots are
      rejected with a clear validation error at construction time — a
      relative root must never silently acquire security meaning from the
      CWD of whatever process happened to construct the validator.

Lifecycle:
    Application startup calls :func:`configure_default_validator_from_config`
    exactly once, passing the :class:`ConfigManager`.  The module-level
    default validator is then used by every file tool via the convenience
    functions :func:`validate_read_path` and :func:`validate_write_path`.

    When the user changes filesystem settings in the Settings dialog,
    ``ConfigManager.set`` is called (which persists to ``settings.json``)
    and ``configure_default_validator_from_config`` is called again to
    apply the new policy without restarting the application.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.logger import get_logger
from core.paths import user_data_root

logger = get_logger("tools.file_security")


class PathValidationError(Exception):
    """Raised when a path fails security validation."""


@dataclass
class ResolvedPath:
    """Result of a successful path validation."""

    original: str
    resolved: Path
    is_within_allowed_root: bool
    action: str  # "read" or "write"


@dataclass
class FilesystemConfig:
    """Configuration for the filesystem security policy.

    Mirrors the ``filesystem`` section in ``settings.json``.
    """

    enabled: bool = True
    read_roots: list[str] = field(default_factory=list)
    write_roots: list[str] = field(default_factory=list)
    follow_symlinks: bool = True

    @classmethod
    def from_config(cls, config: Any) -> FilesystemConfig:
        """Build a :class:`FilesystemConfig` from a :class:`ConfigManager`-like object."""
        return cls(
            enabled=config.get("filesystem.enabled", True),
            read_roots=config.get("filesystem.read_roots", []) or [],
            write_roots=config.get("filesystem.write_roots", []) or [],
            follow_symlinks=config.get("filesystem.follow_symlinks", True),
        )


def _is_link(path: Path) -> bool:
    """True for symlinks AND Windows junctions/reparse points.

    ``Path.is_symlink()`` returns False for NTFS junctions, yet junctions
    are the most common directory-escape vector on Windows (and can be
    created without elevated privileges).  The security policy must treat
    them as links.

    Junction detection is version-robust: ``os.path.isjunction`` exists
    only from Python 3.12; on older interpreters (the verified dev env is
    3.11) the ``st_reparse_point`` stat attribute (Windows, 3.8+) is used
    instead so a junction can never slip past the policy.
    """
    try:
        if path.is_symlink():
            return True
    except OSError:
        return False
    isjunction = getattr(os.path, "isjunction", None)
    if isjunction is not None:
        try:
            return isjunction(path)
        except OSError:
            return False
    # Python < 3.12 fallback: os.lstat on Windows exposes
    # st_file_attributes (stat() would FOLLOW the junction and lose the
    # reparse bit); the FILE_ATTRIBUTE_REPARSE_POINT (0x400) flag is set
    # for junctions (and symlinks, already handled above).
    if os.name == "nt":
        try:
            attrs = os.lstat(path).st_file_attributes
            return bool(attrs & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
        except (OSError, AttributeError):
            return False
    return False


class PathValidator:
    """Validates file paths against a security policy.

    Parameters
    ----------
    read_roots
        Allowed root directories for reading.  When empty, reads from any
        path pass basic sanitisation.  Every root MUST be an absolute path —
        relative roots are rejected at construction (they would otherwise
        derive their meaning from the process CWD).
    write_roots
        Allowed root directories for writing.  When empty and *enabled* is
        True, write operations are denied (Unconfigured state).  Every root
        MUST be an absolute path.
    follow_symlinks
        When True (default), symlinks are followed but the resolved target
        must still be inside an allowed root.  When False, symlinks are
        rejected entirely.
    enabled
        When True (default), filesystem security policy is enforced.
        When False, all paths pass after basic sanitisation (backward
        compatible).  This corresponds to the ``filesystem.enabled`` config
        flag.
    base_dir
        Deterministic base directory against which RELATIVE input paths
        are resolved.  This is the application's user-data root — never
        the process CWD.  When ``None``, relative input paths are rejected
        instead of being resolved against an implicit (CWD-dependent)
        location.
    """

    def __init__(
        self,
        read_roots: list[str | Path] | None = None,
        write_roots: list[str | Path] | None = None,
        follow_symlinks: bool = True,
        enabled: bool = True,
        base_dir: str | Path | None = None,
    ) -> None:
        if base_dir is not None:
            base_path = Path(base_dir)
            if not base_path.is_absolute():
                raise PathValidationError(
                    f"Validator base_dir must be an absolute path: {base_dir}"
                )
            self._base_dir: Path | None = base_path
        else:
            self._base_dir = None

        self._read_roots: list[Path] = []
        for r in read_roots or []:
            if not Path(r).is_absolute():
                raise PathValidationError(
                    f"Read root must be an absolute path; relative roots are "
                    f"rejected because their meaning would depend on the "
                    f"process working directory: {r!r}"
                )
            try:
                self._read_roots.append(Path(r).resolve())
            except (OSError, RuntimeError):
                logger.warning("Could not resolve read root: %s", r)
        self._write_roots: list[Path] = []
        for r in write_roots or []:
            if not Path(r).is_absolute():
                raise PathValidationError(
                    f"Write root must be an absolute path; relative roots are "
                    f"rejected because their meaning would depend on the "
                    f"process working directory: {r!r}"
                )
            try:
                self._write_roots.append(Path(r).resolve())
            except (OSError, RuntimeError):
                logger.warning("Could not resolve write root: %s", r)
        self._follow_symlinks = follow_symlinks
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def read_roots(self) -> list[Path]:
        return list(self._read_roots)

    @property
    def write_roots(self) -> list[Path]:
        return list(self._write_roots)

    @property
    def follow_symlinks(self) -> bool:
        return self._follow_symlinks

    @property
    def base_dir(self) -> Path | None:
        return self._base_dir

    @property
    def has_read_restrictions(self) -> bool:
        return bool(self._read_roots)

    @property
    def has_write_restrictions(self) -> bool:
        return bool(self._write_roots)

    @property
    def is_unconfigured(self) -> bool:
        """True when enabled but no write roots are configured (Unconfigured state)."""
        return self._enabled and not self._write_roots

    def validate_read(self, path: str) -> ResolvedPath:
        """Validate *path* for read operations."""
        return self._validate(path, action="read")

    def validate_write(
        self, path: str, create_parent: bool = False
    ) -> ResolvedPath:
        """Validate *path* for write operations.

        When *create_parent* is True, parent directories are created
        (if they don't exist) before validation.
        """
        return self._validate(path, action="write", create_parent=create_parent)

    def _resolve_absolute(self, raw: Path, path: str) -> Path:
        """Resolve *raw* according to the symlink policy; never uses CWD.

        Relative paths require an explicit deterministic ``base_dir``;
        without one they are rejected rather than CWD-resolved.
        """
        if not raw.is_absolute():
            if self._base_dir is None:
                raise PathValidationError(
                    f"Relative path {path!r} is rejected: no deterministic "
                    f"base directory is configured for this validator. "
                    f"Provide an absolute path."
                )
            raw = self._base_dir / raw
        try:
            if self._follow_symlinks:
                return raw.resolve(strict=False)
            resolved = raw.absolute()
            if _is_link(raw):
                raise PathValidationError(
                    f"Symlinks are not allowed: {path}"
                )
            return resolved
        except (OSError, RuntimeError) as exc:
            raise PathValidationError(
                f"Cannot resolve path '{path}': {exc}"
            ) from exc

    def _validate(
        self, path: str, *, action: str = "read", create_parent: bool = False
    ) -> ResolvedPath:
        if not path or not path.strip():
            raise PathValidationError("Path is empty")

        # Block null bytes
        if "\x00" in path:
            raise PathValidationError("Path contains null bytes")

        raw = Path(path)

        # Reject explicit traversal components in the raw string
        if ".." in raw.parts:
            raise PathValidationError(
                f"Path traversal ('..') not allowed: {path}"
            )

        # Deterministic absolute resolution (see _resolve_absolute)
        resolved = self._resolve_absolute(raw, path)

        # When policy is disabled, allow all (backward compatible)
        if not self._enabled:
            logger.debug("Path validated (%s, policy disabled): %s", action, path)
            return ResolvedPath(
                original=path,
                resolved=resolved,
                is_within_allowed_root=True,
                action=action,
            )

        # Policy is enabled — enforce root containment.
        # For writes, also enforce the "Unconfigured" state.
        if action == "write" and not self._write_roots:
            raise PathValidationError(
                "Filesystem security is enabled but no writable roots are "
                "configured. Please add a writable workspace in Settings."
            )

        # Select appropriate roots
        roots = self._write_roots if action == "write" else self._read_roots

        # If roots are configured, enforce containment of the RESOLVED path
        # (never a string-prefix check — a symlink whose lexical path lies
        # inside a root but whose target escapes it must be denied here).
        if roots:
            allowed = self._is_within_roots(resolved, roots)
            if not allowed:
                root_strs = ", ".join(str(r) for r in roots)
                raise PathValidationError(
                    f"Path '{resolved}' is outside allowed {action} root(s): {root_strs}"
                )
            is_within = True
        else:
            # No roots configured but policy enabled.
            # Reads: allowed (backward compatible).
            # Writes: already denied above.
            is_within = True

        # Create parent directories if requested (write only)
        if create_parent and action == "write":
            try:
                resolved.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise PathValidationError(
                    f"Cannot create parent directory for '{path}': {exc}"
                ) from exc

        logger.debug(
            "Path validated (%s): %s -> %s", action, path, resolved
        )

        return ResolvedPath(
            original=path,
            resolved=resolved,
            is_within_allowed_root=is_within,
            action=action,
        )

    @staticmethod
    def _is_within_roots(path: Path, roots: list[Path]) -> bool:
        """Return True if *path* is equal to or inside any of *roots*."""
        for root in roots:
            try:
                path.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def is_path_authorized(
        self, path: str | Path, action: str = "read"
    ) -> bool:
        """Boolean containment probe for already-resolved candidate paths.

        Used by directory enumeration (e.g. ProjectManager file listing):
        applies the SAME containment + symlink policy as
        :meth:`validate_read` / :meth:`validate_write` without the
        empty-string / traversal / creation semantics that only apply to
        tool input paths.  Must not be used to bypass those checks.
        """
        if action not in ("read", "write"):
            raise ValueError(f"Invalid action: {action!r}")
        if not self._enabled:
            return True
        roots = self._write_roots if action == "write" else self._read_roots
        if action == "write" and not roots:
            # Fail-closed Unconfigured state — same as validate_write.
            return False
        if not roots:
            # Enabled with no roots: reads allowed (backward compatible),
            # writes unreachable (denied above).
            return True
        try:
            resolved = Path(path).resolve(strict=False)
        except (OSError, RuntimeError):
            return False
        if not self._follow_symlinks and _is_link(Path(path)):
            return False
        return self._is_within_roots(resolved, roots)

    def to_config(self) -> dict[str, Any]:
        """Serialize the current policy to a config dict."""
        return {
            "enabled": self._enabled,
            "read_roots": [str(r) for r in self._read_roots],
            "write_roots": [str(r) for r in self._write_roots],
            "follow_symlinks": self._follow_symlinks,
        }


# --------------------------------------------------------------------------- #
# Module-level default validator + configuration lifecycle
# --------------------------------------------------------------------------- #
_default_validator = PathValidator(enabled=False)


def get_default_validator() -> PathValidator:
    """Return the module-level default :class:`PathValidator`."""
    return _default_validator


def validate_read_path(path: str) -> ResolvedPath:
    """Convenience: validate *path* with the default validator for read."""
    return _default_validator.validate_read(path)


def validate_write_path(path: str, create_parent: bool = False) -> ResolvedPath:
    """Convenience: validate *path* with the default validator for write."""
    return _default_validator.validate_write(path, create_parent=create_parent)


def configure_default_validator(
    read_roots: list[str | Path] | None = None,
    write_roots: list[str | Path] | None = None,
    follow_symlinks: bool = True,
    enabled: bool = True,
    base_dir: str | Path | None = None,
) -> PathValidator:
    """Reconfigure the module-level default validator with explicit roots.

    Called once during application startup and again whenever the user
    changes filesystem settings in the Settings dialog.  *base_dir*
    becomes the deterministic resolution base for relative input paths
    (the application user-data root in production).
    """
    global _default_validator
    _default_validator = PathValidator(
        read_roots=read_roots,
        write_roots=write_roots,
        follow_symlinks=follow_symlinks,
        enabled=enabled,
        base_dir=base_dir,
    )
    logger.info(
        "Filesystem policy configured: enabled=%s, read_roots=%d, write_roots=%d, "
        "follow_symlinks=%s, base_dir=%s",
        enabled,
        len(read_roots or []),
        len(write_roots or []),
        follow_symlinks,
        base_dir,
    )
    return _default_validator


def configure_default_validator_from_config(
    config: Any,
) -> PathValidator:
    """Configure the module-level default validator from a ConfigManager.

    The *config* object must support ``.get(key, default)`` with
    dot-separated keys (``filesystem.enabled``, ``filesystem.read_roots`` …).

    Security-relevant behaviour:

    * The deterministic ``base_dir`` is the application user-data root —
      relative input paths resolve against it, never against the CWD.
    * Relative configured roots are DROPPED with a critical log entry
      (they cannot carry deterministic security meaning).  Valid absolute
      roots are kept, so dropping a bad root can only NARROW access,
      never widen it.  Write operations stay fail-closed whenever the
      resulting write-root list is empty.
    """
    fs_config = FilesystemConfig.from_config(config)

    valid_read_roots: list[str] = []
    rejected_read_roots: list[str] = []
    for root in fs_config.read_roots:
        if Path(root).is_absolute():
            valid_read_roots.append(root)
        else:
            rejected_read_roots.append(root)
    valid_write_roots: list[str] = []
    rejected_write_roots: list[str] = []
    for root in fs_config.write_roots:
        if Path(root).is_absolute():
            valid_write_roots.append(root)
        else:
            rejected_write_roots.append(root)

    if rejected_read_roots or rejected_write_roots:
        logger.critical(
            "Rejected relative filesystem roots (relative roots are not "
            "deterministic and are refused): read=%r write=%r",
            rejected_read_roots,
            rejected_write_roots,
        )

    return configure_default_validator(
        read_roots=valid_read_roots,
        write_roots=valid_write_roots,
        follow_symlinks=fs_config.follow_symlinks,
        enabled=fs_config.enabled,
        base_dir=user_data_root(),
    )


# Backward-compatible alias
configure_default = configure_default_validator
