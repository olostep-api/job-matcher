from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
JOBS_PATH = DATA_DIR / "jobs.json"
