from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(slots=True)
class ResumeProfile:
    name: str
    skills: List[str]
    technologies: List[str]
    years_experience: float
    roles: List[str]
    education: List[str]
    keywords: List[str]
