from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List

from src.job_matcher.agent import run_agent_workflow
from models.job import Job


def run_job_matcher(resume_path: Path, jobs_path: Path, olostep_api_key: str) -> List[Job]:
    return asyncio.run(
        run_agent_workflow(
            resume_path=resume_path,
            jobs_path=jobs_path,
            olostep_api_key=olostep_api_key,
        )
    )
