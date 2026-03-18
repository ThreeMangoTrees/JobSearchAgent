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


class CompanyConfig(BaseModel):
    company_slug: str = Field(..., description="Filesystem-safe company identifier.")
    company_name: str = Field(..., description="Display name for the company.")
    careers_page_url: str = Field(..., description="Company careers page URL.")
    extraction_instructions: str = Field(..., description="Admin-provided extraction instructions.")
    created_at: str = Field(..., description="ISO timestamp when the config was created.")
    updated_at: str = Field(..., description="ISO timestamp when the config was updated.")
    last_scraped_at: str = Field(default="", description="ISO timestamp for the latest scrape.")
    last_extracted_at: str = Field(default="", description="ISO timestamp for the latest job extraction.")


class ExtractedJob(BaseModel):
    job_id: str = Field(..., description="Unique job identifier.")
    location: str = Field(..., description="Job location.")
    role_name: str = Field(..., description="Job role name.")
