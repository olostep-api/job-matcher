from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class Job(BaseModel):
    title: str
    company: str
    location: str
    description: str
    required_skills: List[str] = Field(default_factory=list)
    posting_date: Optional[datetime] = None
    job_url: str
    hiring_probability: Optional[float] = None
    match_reason: List[str] = Field(default_factory=list)

    def dedupe_key(self) -> str:
        return f"{self.title.strip().lower()}|{self.company.strip().lower()}|{self.job_url.strip().lower()}"
