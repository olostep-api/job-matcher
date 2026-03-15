from __future__ import annotations

from pathlib import Path

# Default resume path used by UI and CLI when no upload/custom path is provided.
RESUME_PATH = Path(__file__).resolve().parent / "data" / "resume.md"
