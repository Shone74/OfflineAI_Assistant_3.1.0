"""Shared pytest configuration for Offline AI Assistant tests.

Sets test-mode environment variables BEFORE any project import so that the
application runs headless with stub engines (no GPU / model files needed):
- OFFLINE_AI_TEST_MODE=1 -> StubModelLoader / StubEngine fallbacks
- QT_QPA_PLATFORM=offscreen -> headless Qt for CI
"""

from __future__ import annotations

import os

os.environ.setdefault("OFFLINE_AI_TEST_MODE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
