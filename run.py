"""Offline AI Assistant — final application launcher."""

from __future__ import annotations

import os
import sys


def _app_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _prepare_paths(app_root: str) -> None:
    if app_root not in sys.path:
        sys.path.insert(0, app_root)


def main() -> int:
    app_root = _app_root()
    _prepare_paths(app_root)
    os.environ.setdefault("QT_QPA_PLATFORM", "windows")
    from app.application_final import main as app_main
    return app_main()


if __name__ == "__main__":
    sys.exit(main())
