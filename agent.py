from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from dotenv import load_dotenv

try:
    from agents import Agent, Runner, function_tool
except Exception as exc:  # noqa: BLE001
    raise RuntimeError(
        "openai-agents is required. Install with: pip install openai-agents"
    ) from exc

from models.job import Job
from models.resume import ResumeProfile
from tools.job_parser import extract_skills_from_text, parse_resume_markdown
from tools.job_search import scrape_jobs, search_jobs
from tools.scoring import compute_hiring_odds_hybrid

logger = logging.getLogger(__name__)


class JobStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> List[Job]:
        if not self.path.exists():
            return []
        content = self.path.read_text(encoding="utf-8").strip()
        if not content:
            return []
        try:
            raw = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in %s. Resetting job cache to empty list.", self.path)
            self.path.write_text("[]\n", encoding="utf-8")
            return []
        return [Job(**item) for item in raw]

    def save_jobs(self, new_jobs: List[Job]) -> List[Job]:
        existing = self.load()
        by_key = {job.dedupe_key(): job for job in existing}
        for job in new_jobs:
            by_key[job.dedupe_key()] = job

        merged = list(by_key.values())
        merged.sort(key=lambda j: (j.hiring_probability or 0.0), reverse=True)
        payload = [job.model_dump(mode="json") for job in merged]
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return merged


def _raw_job_identifier(raw: Dict[str, Any]) -> str:
    title = raw.get("title") or raw.get("job_title") or "unknown-title"
    job_url = raw.get("url") or raw.get("job_url") or raw.get("link") or "unknown-url"
    return f"title={title!r}, url={job_url!r}"


def parse_olostep_result(raw: Dict[str, Any]) -> Job | None:
    title = raw.get("title") or raw.get("job_title")
    company = raw.get("company") or raw.get("company_name")
    description = raw.get("description") or raw.get("snippet") or ""
    job_url = raw.get("url") or raw.get("job_url") or raw.get("link") or ""

    if not company and job_url:
        domain = urlparse(job_url).netloc.lower().replace("www.", "")
        company = domain.split(".")[0].replace("-", " ").title() if domain else "Unknown"

    if not title or not job_url or not description.strip():
        return None

    location = raw.get("location") or "Unknown"
    required_skills = extract_skills_from_text(description)

    return Job(
        title=title,
        company=company,
        location=location,
        description=description,
        required_skills=required_skills,
        job_url=job_url,
    )


def build_agent(olostep_api_key: str, jobs_path: str | Path):
    _ = JobStore(jobs_path)
    state: Dict[str, Any] = {"resume_read": False}

    @function_tool
    def read_resume(path: str) -> dict:
        if state["resume_read"]:
            return {"error": "Resume has already been read. Reuse the previous parsed profile."}
        profile = parse_resume_markdown(path)
        state["resume_read"] = True
        return profile.__dict__

    @function_tool
    def search_jobs_tool(profile_json: str) -> list[dict]:
        profile = ResumeProfile(**json.loads(profile_json))
        return search_jobs(profile=profile, api_key=olostep_api_key)

    @function_tool
    def scrape_jobs_tool(raw_results_json: str) -> list[dict]:
        raw_results = json.loads(raw_results_json)
        if not isinstance(raw_results, list):
            return []
        items = [item for item in raw_results if isinstance(item, dict)]
        return scrape_jobs(items, api_key=olostep_api_key)

    instructions = (
        "You are JobMatcherAgent with 3 tools only: read_resume, search_jobs_tool, scrape_jobs_tool. "
        "Call read_resume exactly once at the start. "
        "You may call search_jobs_tool and scrape_jobs_tool multiple times."
    )

    return Agent(
        name="JobMatcherAgent",
        instructions=instructions,
        tools=[read_resume, search_jobs_tool, scrape_jobs_tool],
    )


async def run_agent_workflow(resume_path: str | Path, jobs_path: str | Path, olostep_api_key: str) -> List[Job]:
    load_dotenv()

    profile = parse_resume_markdown(resume_path)
    raw_jobs = search_jobs(profile, api_key=olostep_api_key)
    logger.info("Fetched %s raw search results", len(raw_jobs))
    raw_jobs = scrape_jobs(raw_jobs, api_key=olostep_api_key)
    logger.info("Scraped %s job pages for missing descriptions", len(raw_jobs))

    parsed_jobs: List[Job] = []
    skip_counts = {
        "missing_title": 0,
        "missing_url": 0,
        "missing_description": 0,
    }
    for raw in raw_jobs:
        title = raw.get("title") or raw.get("job_title")
        job_url = raw.get("url") or raw.get("job_url") or raw.get("link")
        description = raw.get("description") or raw.get("snippet") or ""

        if not title:
            skip_counts["missing_title"] += 1
            logger.info("Skipping raw result: missing title (%s)", _raw_job_identifier(raw))
            continue
        if not job_url:
            skip_counts["missing_url"] += 1
            logger.info("Skipping raw result: missing url (%s)", _raw_job_identifier(raw))
            continue
        if not str(description).strip():
            skip_counts["missing_description"] += 1
            logger.info("Skipping raw result: missing description (%s)", _raw_job_identifier(raw))
            continue

        job = parse_olostep_result(raw)
        if job is None:
            logger.info("Skipping raw result: parse failed (%s)", _raw_job_identifier(raw))
            continue

        score, reasons = compute_hiring_odds_hybrid(profile, job)
        job.hiring_probability = score
        job.match_reason = reasons
        parsed_jobs.append(job)

    store = JobStore(jobs_path)
    merged = store.save_jobs(parsed_jobs)

    merged.sort(key=lambda x: x.hiring_probability or 0.0, reverse=True)

    # Initialize agent object for SDK architecture compliance and future orchestration.
    _ = build_agent(olostep_api_key=olostep_api_key, jobs_path=jobs_path)

    logger.info(
        "Job filtering summary: kept=%s, missing_title=%s, missing_url=%s, missing_description=%s",
        len(parsed_jobs),
        skip_counts["missing_title"],
        skip_counts["missing_url"],
        skip_counts["missing_description"],
    )
    logger.info("Processed %s jobs, returning top %s", len(merged), min(10, len(merged)))
    return merged[:10]
