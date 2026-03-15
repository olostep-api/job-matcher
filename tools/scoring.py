from __future__ import annotations

import os
import json
import logging
import math
import re
from datetime import datetime
from typing import List, Tuple

import numpy as np

from models.job import Job
from models.resume import ResumeProfile
from utils.date_utils import days_since

logger = logging.getLogger(__name__)

try:
    from openai import OpenAI
except Exception:  # noqa: BLE001
    OpenAI = None  # type: ignore[assignment]


LEVEL_TO_EXPERIENCE = {
    "intern": 0,
    "junior": 1,
    "associate": 2,
    "mid": 3,
    "senior": 5,
    "staff": 7,
    "lead": 8,
    "principal": 10,
}


def _infer_expected_experience(job: Job) -> float:
    text = f"{job.title} {job.description}".lower()
    match = re.search(r"(\d+(?:\.\d+)?)\+?\s+years?", text)
    if match:
        return float(match.group(1))

    for level, years in LEVEL_TO_EXPERIENCE.items():
        if level in text:
            return float(years)
    return 3.0


def _skill_score(resume: ResumeProfile, job: Job) -> float:
    required = {s.strip().lower() for s in job.required_skills if s.strip()}
    if not required:
        return 0.5
    candidate = {s.strip().lower() for s in resume.skills}
    return len(required.intersection(candidate)) / len(required)


def _experience_score(resume: ResumeProfile, expected: float) -> float:
    if expected <= 0:
        return 1.0
    ratio = resume.years_experience / expected if expected else 1.0
    return float(np.clip(ratio, 0.0, 1.0))


def _recency_score(posting_date: datetime | None) -> float:
    d = days_since(posting_date)
    return float(math.exp(-d / 30.0))


def compute_hiring_odds(resume: ResumeProfile, job: Job) -> Tuple[float, List[str]]:
    skill_score = _skill_score(resume, job)
    expected_exp = _infer_expected_experience(job)
    exp_score = _experience_score(resume, expected_exp)
    recency = _recency_score(job.posting_date)

    final = 0.5 * skill_score + 0.3 * exp_score + 0.2 * recency

    reasons: List[str] = []
    if skill_score >= 0.7:
        reasons.append("Strong skills overlap")
    elif skill_score >= 0.4:
        reasons.append("Moderate skills overlap")
    else:
        reasons.append("Low skills overlap")

    if exp_score >= 0.8:
        reasons.append("Experience aligns with role")
    elif expected_exp > resume.years_experience:
        reasons.append("Experience slightly below preferred level")

    recency_days = days_since(job.posting_date)
    reasons.append(f"Posted {recency_days} days ago")

    return float(np.clip(final, 0.0, 1.0)), reasons


def _compute_hiring_odds_openai(resume: ResumeProfile, job: Job) -> Tuple[float, List[str]] | None:
    if OpenAI is None:
        return None

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    posting_date_text = job.posting_date.date().isoformat() if job.posting_date else "unknown"
    resume_payload = {
        "name": resume.name,
        "skills": resume.skills,
        "technologies": resume.technologies,
        "years_experience": resume.years_experience,
        "roles": resume.roles,
        "education": resume.education,
        "keywords": resume.keywords[:20],
    }
    job_payload = {
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "posting_date": posting_date_text,
        "job_description": job.description[:12000],
        "required_skills": job.required_skills,
    }

    prompt = (
        "You are an expert recruiting analyst. Estimate the probability that the candidate gets a first interview.\n"
        "Return ONLY strict JSON with keys: probability (number 0..1), reasons (array of 2-4 short strings).\n"
        "Use resume-job relevance and posting recency. Be realistic and calibrated.\n\n"
        f"ResumeProfile: {json.dumps(resume_payload)}\n"
        f"Job: {json.dumps(job_payload)}\n"
    )

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": "Return only valid JSON. Do not wrap JSON in markdown fences.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        )
        text = (response.choices[0].message.content or "").strip()
        parsed = json.loads(text)
        probability = float(parsed.get("probability", 0.0))
        reasons_raw = parsed.get("reasons", [])
        reasons = [str(r).strip() for r in reasons_raw if str(r).strip()][:4]
        probability = float(np.clip(probability, 0.0, 1.0))
        if not reasons:
            reasons = ["Model-based interview likelihood estimate"]
        return probability, reasons
    except Exception as exc:  # noqa: BLE001
        logger.warning("OpenAI hiring odds failed, falling back to heuristic scoring: %s", exc)
        return None


def compute_hiring_odds_hybrid(resume: ResumeProfile, job: Job) -> Tuple[float, List[str]]:
    model_score = _compute_hiring_odds_openai(resume, job)
    if model_score is not None:
        return model_score
    return compute_hiring_odds(resume, job)
