from __future__ import annotations

from pydantic import BaseModel, Field


class JobMatch(BaseModel):
    job_id: str = Field(..., description="The job identifier from the scraped posting.")
    title: str = Field(..., description="The job title.")
    location: str = Field(..., description="The job location from the posting.")
    company_url: str = Field(..., description="The company career page or site.")
    source_url: str = Field(..., description="The scraped job posting URL.")
    reason: str = Field(..., description="Why the role fits the resume.")


class MatchResult(BaseModel):
    matches: list[JobMatch] = Field(default_factory=list)
    notes: str = Field(..., description="Important caveats about the matching result.")
