from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from settings import RESUME_PATH
from src.job_matcher.constants import JOBS_PATH
from src.job_matcher.service import run_job_matcher


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run job matcher once from CLI")
    parser.add_argument("--resume", default=str(RESUME_PATH), help="Path to resume file (.md or .pdf)")
    parser.add_argument("--jobs", default=str(JOBS_PATH), help="Path to jobs JSON output")
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()

    olostep_api_key = os.getenv("OLOSTEP_API_KEY", "").strip()
    if not olostep_api_key:
        raise RuntimeError("Missing OLOSTEP_API_KEY in environment")

    jobs = run_job_matcher(
        resume_path=Path(args.resume).expanduser().resolve(),
        jobs_path=Path(args.jobs).expanduser().resolve(),
        olostep_api_key=olostep_api_key,
    )

    output = [
        {
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "description": job.description,
            "hiring_probability": round(job.hiring_probability or 0.0, 4),
            "job_url": job.job_url,
            "match_reason": job.match_reason,
        }
        for job in jobs
    ]
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
