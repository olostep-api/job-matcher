from __future__ import annotations

import base64
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Iterable, List

try:
    from openai import OpenAI
except Exception:  # noqa: BLE001
    OpenAI = None  # type: ignore[assignment]

from models.resume import ResumeProfile
from utils.pdf_to_markdown import pdf_to_markdown


KNOWN_SKILLS = {
    "python",
    "pytorch",
    "tensorflow",
    "scikit-learn",
    "numpy",
    "pandas",
    "sql",
    "aws",
    "gcp",
    "azure",
    "docker",
    "kubernetes",
    "fastapi",
    "flask",
    "ml",
    "machine learning",
    "deep learning",
    "nlp",
    "llm",
    "langchain",
    "spark",
    "airflow",
}

ROLE_HINTS = {
    "engineer",
    "developer",
    "scientist",
    "analyst",
    "manager",
    "lead",
    "architect",
}

EDU_HINTS = {"bsc", "msc", "phd", "bachelor", "master", "university", "college"}


def _tokens(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9+\-\.]+", text.lower())


def extract_skills_from_text(text: str, seed_skills: Iterable[str] | None = None) -> List[str]:
    lower = text.lower()
    skills = set(seed_skills or [])
    for skill in KNOWN_SKILLS:
        if skill in lower:
            skills.add(skill)
    return sorted(skills)


def estimate_years_experience(text: str) -> float:
    patterns = [
        r"(\d+(?:\.\d+)?)\+?\s+years?\s+of\s+experience",
        r"experience\s+of\s+(\d+(?:\.\d+)?)\+?\s+years?",
        r"(\d+(?:\.\d+)?)\+?\s+yrs",
    ]
    lower = text.lower()
    for pattern in patterns:
        match = re.search(pattern, lower)
        if match:
            return float(match.group(1))
    return 0.0


def _resume_from_json_payload(payload: dict) -> ResumeProfile:
    return ResumeProfile(
        name=str(payload.get("name") or "Unknown Candidate"),
        skills=[str(x).strip() for x in payload.get("skills", []) if str(x).strip()],
        technologies=[str(x).strip() for x in payload.get("technologies", []) if str(x).strip()],
        years_experience=float(payload.get("years_experience") or 0.0),
        roles=[str(x).strip() for x in payload.get("roles", []) if str(x).strip()],
        education=[str(x).strip() for x in payload.get("education", []) if str(x).strip()],
        keywords=[str(x).strip() for x in payload.get("keywords", []) if str(x).strip()],
    )


def _parse_pdf_with_openai(resume_path: Path) -> ResumeProfile:
    if OpenAI is None:
        raise RuntimeError("openai package is not installed")

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY for PDF resume parsing")

    b64_pdf = base64.b64encode(resume_path.read_bytes()).decode("ascii")
    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model="gpt-4.1-mini",
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Extract this resume into strict JSON only with keys: "
                            "name, skills, technologies, years_experience, roles, education, keywords. "
                            "Use arrays of strings except years_experience (number)."
                        ),
                    },
                    {
                        "type": "input_file",
                        "filename": resume_path.name,
                        "file_data": f"data:application/pdf;base64,{b64_pdf}",
                    },
                ],
            }
        ],
    )
    text = (getattr(response, "output_text", "") or "").strip()
    if not text:
        raise RuntimeError("OpenAI returned empty resume parse output")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise RuntimeError("OpenAI resume parse did not return a JSON object")
    return _resume_from_json_payload(payload)


def parse_resume_markdown(path: str | Path) -> ResumeProfile:
    resume_path = Path(path)
    if resume_path.suffix.lower() == ".pdf":
        try:
            return _parse_pdf_with_openai(resume_path)
        except Exception:  # noqa: BLE001
            resume_path = pdf_to_markdown(resume_path)
    content = resume_path.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.splitlines() if line.strip()]

    name = lines[0].lstrip("# ") if lines else "Unknown Candidate"
    lower_content = content.lower()

    skills = extract_skills_from_text(content)
    years_experience = estimate_years_experience(content)

    roles = sorted({token for token in _tokens(content) if token in ROLE_HINTS})
    education_lines = [line for line in lines if any(hint in line.lower() for hint in EDU_HINTS)]

    words = [t for t in _tokens(lower_content) if len(t) > 2]
    common_keywords = [w for w, _ in Counter(words).most_common(30)]

    technologies = [s for s in skills if s in {"python", "pytorch", "tensorflow", "aws", "gcp", "azure", "docker", "kubernetes", "sql", "spark", "airflow", "fastapi", "flask"}]

    return ResumeProfile(
        name=name,
        skills=skills,
        technologies=technologies,
        years_experience=years_experience,
        roles=roles,
        education=education_lines,
        keywords=common_keywords,
    )
